# Mục "⚠️ Rủi ro cần lưu ý" theo phơi nhiễm danh mục (risk_today) — ĐẶC TẢ, CHƯA CODE

> **Trạng thái: ✅ CODE XONG 06/10/2026 (nhánh `claude/vibrant-maxwell-4g4edj`, CLAUDE-NOTES U75) — user trả lời: câu 1 = (b) bỏ khối cực trị khỏi brief ngày, in lại khi có KỲ BCTC MỚI (pha 2, chưa code); câu 2 = CÓ tính 16 lệnh footer là phơi nhiễm. Lệch so với đặc tả: hàm canon tên `_fmt_footer_price` (`vnstock_brief` đã có `_fmt_rec_price` khác hành vi); `_exposure_tickers` gồm MỌI lệnh mở (cả lệnh ẩn — reconcile U74 cần lịch GDKHQ của chúng); test brief_watch/doctor/universe nằm trong `tests/test_brief_risk_today.py` + `tests/test_rec_corp_action.py`.** Bản đề xuất 05/10: Sinh từ workflow 38 agent (2 người đánh giá brief 05/10 × phản biện từng phát hiện, 1 người dò code, 3 thiết kế độc lập × 3 giám khảo, 1 tổng hợp). Lý do: khối "Đòn bẩy cao nhất VTZ/VJC/PET · Op.CF thấp nhất KBC/NVL" lặp y hệt nhiều tháng (user 05/10).

## Vì sao khối cũ lặp mãi (đã kiểm code)

Khối lặp y hệt vì 5 lý do cộng dồn, đều nằm trong code:

1) DỮ LIỆU TĨNH THEO NĂM. Op.CF khoá vào năm tài chính đã đóng (FY2025 tới 01/01/2027), D/E là kỳ năm. Fetch lại mỗi tuần cũng chỉ chép lại cùng con số.

2) PHÉP CHỌN LÀ XẾP HẠNG CỰC TRỊ trên một nhóm lớn và ổn định: VN30 ∪ vài trăm mã ≥ 10 tỷ. `_canonical_risk_lines` (guards_sections.py:1029-1059) lấy top-3 D/E ≥ 1.5 và top-2 Op.CF âm. Mã cực trị (VTZ/VJC/PET, KBC/NVL) chỉ rời bảng khi tụt dưới sàn thanh khoản. Hàm không có khái niệm "mới", "đổi so với hôm qua", hay "liên quan hôm nay".

3) KHÔNG NỐI VỚI GÌ CỦA NGÀY. Hàm chỉ đọc vn30_fundamentals, financial_tickers và realestate_tickers. Nó không xét portfolio (EIB/SSI, mà cả hai còn bị loại vì là tài chính), watchlist (SSB/DCM/VPI), khuyến nghị mở, GDKHQ, khối ngoại, vĩ mô, độ rộng hay giá. Rủi ro hằng năm được trình bày như rủi ro của phiên.

4) GUARD CHÈN VÔ ĐIỀU KIỆN VÀ XOÁ PHẦN SỐNG. `enforce_risk_section` (sections.py:1092-1093) luôn nối khối canonical khi có fundamentals, kể cả khi template nói "block không có mã đáng lưu ý → nêu rủi ro vĩ mô/kỹ thuật". Tệ hơn, `_is_fundamental` (:1086-1089) xoá mọi dòng model viết có nhắc BẤT KỲ mã nào trong nhóm vài trăm mã (EIB, SSI, VIC, SSB, GMD…) hoặc chữ "đòn bẩy". ⇒ Rủi ro cụ thể theo mã của ngày (danh mục lỗ, Họ VIN phân phối, GDKHQ mã đang giữ) bị lọc mất. Thứ sống sót chỉ là 1–2 câu vĩ mô không mã, cộng khối tĩnh (đã chạy thử: brief_guards_sections, ctx giả).

5) PROMPT CŨNG ĐẨY MODEL VỀ ĐÓ. Template :345 / :257 dành gần hết chỉ dẫn mục Rủi ro cho luật D/E/Op.CF ("CHỈ nêu rủi ro cơ bản bằng mã lấy TỪ dòng 'Đòn bẩy cao nhất'…"), nên model mặc định viết đúng khối này. Phần khác chỉ là một dòng "[Red flags, distribution, macro risk…]". Hai bên còn lệch nhau nhỏ: prompt đưa top-3 D/E không lọc ≥ 1.5 và top-3 Op.CF, còn canonical lấy ≥ 1.5 và top-2.

LIÊN QUAN THIẾT KẾ 3 KHUNG (docs/THIET-KE-BRIEF-3-KHUNG.md)
- Tài liệu KHÔNG đụng tới mục "Rủi ro cần lưu ý" (grep 0 hit), nên P1b sẽ không tự chữa khối tĩnh này.
- 🚨 được tài liệu đặt ở header/🔭 (§3.7). Theo luật §3.7, ngày 05/10 🚨 vẫn BẬT mức 1: neo 1,853.08 từ 01/10, close 1,753.2 = 94.6% neo, dưới MA20, mới 3 phiên trong khi muốn tắt cần ≥ 5 phiên. Vậy mà brief 05/10 không có dòng nào về sụt từ đỉnh, mục Rủi ro thì nói D/E năm.
- Header còn "Bear — Risk-off" mà tài liệu bỏ: P1b chưa làm, đúng tiến độ.
- 📌 SSI "GIỮ" neo vào S1 VNINDEX, chưa có trạng thái MA50 và band B4 15% như mẫu (C) của tài liệu.


**Nguồn & nhịp dữ liệu:**

NGUỒN: `vnstock_fundamental_updater.py` (VCI qua vnstock) → `data_warehouse/_meta/fundamentals.parquet`. File nằm trong kho Dropbox nên hai máy dùng chung. Mỗi tháng còn lưu thêm một ảnh chụp ở `_meta/fundamentals_history/fundamentals-YYYY-MM.parquet` (`_archive_monthly_snapshot` :127, bản đầu tháng thắng).

LỊCH CHẠY
- Chạy LẠI hằng tuần: task Weekend (T7 09:00, chỉ 🖥️ desktop) gọi `run.py weekend` → `_weekend_steps` (run.py:1250-1270) chạy `vnstock_fundamental_updater.py --force --workers 4 --delay 1`. Có `--force` thì mọi mã đều fetch lại.
- Badge doctor `check_fundamentals` (vnstock_doctor.py:721-733) xanh khi mtime ≤ 10 ngày.

NHƯNG SỐ LIỆU LÀ SỐ NĂM, nên tuần nào fetch lại cũng ra y hệt:
- Op.CF: `_annual_operating_cf` (:363-416) chọn NĂM TÀI CHÍNH ĐÃ ĐÓNG gần nhất, tức năm < năm lịch hiện tại (`complete = [y < cur]`). Năm 2026 thì đó là FY2025, và con số đứng yên tới 01/01/2027. KBC -17,344 tỷ chính là FY2025 (CLAUDE-NOTES:83-89). Trong khi đó số TTM thật đã khác: −16.510 tỷ, user tra BCTC Finhay ngày 29/09, ghi ở VIEC-DANG-LAM.md dòng 5.
- D/E: `_fetch_ratios` gọi `_RATIO_PARAMS` (:151) với period="year", rồi `_best_ratio_row` (:279) lấy kỳ năm mới nhất có số. Ngân hàng thì dự phòng bằng `_fetch_debt_to_equity` (:458), tính từ bảng cân đối năm. ⇒ D/E chỉ đổi khi có BCTC năm mới, ~1 lần/năm vào Q1–Q2.
- Nhãn "(cập nhật {updated})" trong khối prompt là NGÀY FETCH (tuần), không phải kỳ BCTC ⇒ trông như số tươi trong khi là FY2025. Dòng canonical thì không ghi kỳ nào cả.

UNIVERSE: VN30 (hằng `VN30_TICKERS`, vnstock_brief_canon.py:46-50) ∪ mọi mã GTGD TB ≥ 10 tỷ và giá ≥ 5. Nhóm `_FINANCIAL_TICKERS` (canon:57-71, có EIB, SSI, TCX) và mã ngành tài chính bị LOẠI khỏi xếp hạng. Danh mục user (EIB, SSI) vì thế không bao giờ được mục này nhắc.

PHÁT HIỆN PHỤ (đã kiểm, đã mở thẻ việc task_d79f6e88): `tests/test_fundamental_cf.py::_run_update` monkeypatch `FUND_PATH` nhưng KHÔNG monkeypatch `FUND_HISTORY_DIR`. Hậu quả:
- `_save` → `_archive_monthly_snapshot` ghi ảnh chụp giả AAA/BBB/CCC (de 1.5, ocf 1234) vào kho THẬT. Sandbox đang có đúng file `fundamentals-2026-10.parquet` 3 dòng đó.
- Bước `test` của `run.py all` chạy bộ ĐẦY ĐỦ lúc 18:00 ngày làm việc, trước Weekend. Vì bản đầu tháng thắng, ảnh chụp point-in-time thật của tháng có thể đã bị rác chiếm (○ kiểm một lần trên kho).


**Lịch sử (vì sao mục này bị chốt bằng guard):**

Nguồn: docs/CLAUDE-NOTES.md và docstring của guard/test. Git sandbox shallow (115 commit, từ 15/09) nên không truy được commit gốc.

- ~05–06/06/2026: thêm khối "Cơ bản nhóm theo dõi" (VN30 D/E/ROE/Op.CF) vào prompt cho mục Rủi ro (test_build_prompt_includes_fundamentals_block, ngày 2026-06-05). Sau đó nới universe sang mid-cap thanh khoản. Từ đây model mắc liên tục các lỗi sau (ghi trong docstring `enforce_risk_numbers` và test_brief.py:1843-2050):
  - nêu mã không kèm số (15:27 "HNG, PET, VTZ có D/E cao");
  - gán số của mã khác (23:08 "KBC D/E=8.83" — 8.83 là của HNG; "HPG D/E=1.55" trong khi thật là 0.65);
  - chọn nhầm mã D/E thấp làm rủi ro (09:02 "HPG D/E=0.65 … rủi ro cơ bản");
  - superlative sai (11:19 "PET và VTZ có D/E cao nhất 2.67/2.63" trong khi HNG = 8.83);
  - nêu mã ngoài data (VCK);
  - nói "cần thêm dữ liệu";
  - gọi Op.CF ≥ 0 là "âm";
  - gắn cờ ngân hàng ("MBB Op.CF -64,972 tỷ") ⇒ thêm `_FINANCIAL_TICKERS`, rồi lọc thêm theo ngành;
  - bỏ ngữ cảnh BĐS, gọi "kiệt quệ tiền mặt" (13:50 có ngữ cảnh, 14:48 nêu trơn KBC/NVL).
- 10/06: chốt "BĐS Op.CF — ngữ cảnh, KHÔNG loại". KBC FY2025 −17.344 tỷ là SỐ THẬT; LN HĐKD trước vốn lưu động +539 tỷ (CLAUDE-NOTES:83-90). Thêm `enforce_realestate_ocf_context`.
- 11/06: brief sáng cũng có mục Rủi ro, cùng luật (parity, CLAUDE-NOTES:407).
- 12/06: gom thành `apply_brief_guards` dùng chung. `enforce_risk_section` thành guard đầu tiên của mục Rủi ro và CANONICAL-HOÁ: bỏ toàn bộ claim cơ bản của LLM, thay bằng `_canonical_risk_lines`. Hai guard cũ thành no-op phòng thủ (CLAUDE-NOTES:121-153). Lý do ghi trong docstring: các lỗi đó "none of which it actually needs to author — the facts are fully data-driven".
- 15/07 01:10: `enforce_macro` cướp mục Rủi ro (câu văn xuôi "Rủi ro vĩ mô: lãi suất…") và nuốt dòng D/E ⇒ anchor 2 nấc (CLAUDE-NOTES:343-348, test_close_1507_0110_fixes).
- 21–22/08 (U22): nghi KBC Op.CF quá lớn so với vốn hoá ⇒ chuyển sang ĐẾM bằng `vnstock_brief_watch.scan_ocf_scale` (U23, CLAUDE-NOTES:10961). TCX vào `_FINANCIAL_TICKERS` khi vào VN30 kỳ 08/2026.
- 07/09 (U54): sổ Op.CF loại nhóm tài chính. Ghi chú rõ "KBC (BĐS) vẫn được giữ — Op.CF âm nặng do tích luỹ quỹ đất là tín hiệu THẬT mà mục Rủi ro sinh ra để nói" (CLAUDE-NOTES:8669).
- 09/09 (U55): chuỗi "Op.CF âm của mã (BĐS)" được ghi là chữ trúc trắc, không phải lỗi (CLAUDE-NOTES:8589).
- 29/09: sổ đủ mẫu, đối chiếu Finhay ⇒ KBC/PVC là SỐ THẬT, xoá brief_watch.json để đếm lại (VIEC-DANG-LAM:669).
- 30/09 (U64): brief Claude đầu tiên chấm 4★, có câu "Rủi ro neo D/E + Op.CF, ghi chú BĐS chuẩn".

⇒ Guard sinh ra để chặn BỊA/SAI số, và nó làm được việc đó. Chưa có mục ghi chép nào bàn tới việc khối này LẶP mỗi ngày, hay việc nó lọc mất rủi ro theo mã của ngày.


## Chấm 3 thiết kế

- Giám khảo 1: chọn **Rủi ro theo Góc LIÊN QUAN (risk-relevance): số cơ bản chỉ in cho mã user đang dính, và chỉ khi có gì MỚI** — Rủi ro theo Góc LIÊN QUAN (risk-relevance)… 30; Rủi ro theo phiên + Cơ bản theo sự kiện (risk… 23.5; Rủi ro hôm nay theo phơi nhiễm danh mục (risk… 28.5
- Giám khảo 2: chọn **Rủi ro hôm nay theo phơi nhiễm danh mục (risk_today)** — Rủi ro theo Góc LIÊN QUAN (risk-relevance)… 29; Rủi ro theo phiên + Cơ bản theo sự kiện (risk… 22; Rủi ro hôm nay theo phơi nhiễm danh mục (risk… 30
- Giám khảo 3: chọn **Rủi ro hôm nay theo phơi nhiễm danh mục (risk_today)** — Rủi ro theo Góc LIÊN QUAN (risk-relevance)… 29; Rủi ro theo phiên + Cơ bản theo sự kiện (risk… 25; Rủi ro hôm nay theo phơi nhiễm danh mục (risk… 30

## Thiết kế chọn

Gốc: thiết kế 3 "Rủi ro hôm nay theo phơi nhiễm danh mục (risk_today)".
- Tổng điểm 3 giám khảo: 28.5 + 30 + 30 = 88.5. risk-relevance được 30 + 29 + 29 = 88, risk-delta được 70.5.
- 2/3 giám khảo chọn risk_today.
- Lý do chọn: an toàn số liệu cao nhất (code sở hữu mọi con số trong mục), dám bỏ cả dạng lặp thứ hai (gauge mức VN10Y−US10Y), và bắt được hai lỗi thật: EIB thuộc 'Họ M'; adjusted_price nhận ĐỒNG.

Ghép từ các bản khác:
(1) Từ risk-relevance:
- Chế độ ghi vào ctx['risk_today'], guard KHÔNG đọc env. Nhờ vậy guard vẫn là hàm thuần (text, ctx), pack và `--from-file` tái lập đúng chế độ của đêm xuất. ctx thiếu khoá thì chạy nhánh cũ giống từng byte, nên không test cũ nào phải sửa.
- Guard dựng mục đặt SAU enforce_reference_band_wording.
- Cửa sổ GDKHQ neo theo ctx['date'].
- Dòng code nhận diện bằng tiền tố cố định, để idempotent.
- Cấm chữ 'cao nhất'.
- Header khối cơ bản thôi ghi '(cập nhật …)'.
- ctx['open_recs'] dùng đúng luật split_recs_by_validation như footer.
(2) Từ risk-delta:
- Mở universe sự kiện và cơ bản thêm danh mục ∪ lệnh mở. (06/10: phần SỰ KIỆN ∪ LỆNH MỞ đã làm ở nhánh `claude/vibrant-maxwell-4g4edj` — `_events_universe(extra_tickers=)` đúng chữ ký dưới đây + `_open_rec_tickers()`, test ở `tests/test_rec_corp_action.py`; còn danh mục + cơ bản.)
- Sửa corp_ratio cho 'Cổ phiếu thưởng'. Khớp theo chữ CÓ DẤU, vì bỏ dấu thì 'thưởng' trùng 'thường'.
- Đếm 'mục Rủi ro lặp y hệt' bằng brief_watch.

Những gì đã BỎ so với bản gốc:
- M1/M2 (hồi thiếu xác nhận, ngày phân phối): chép lại số đã có ở TLDR/Tổng kết, và dẫm lên dòng 🔭 Ngắn hạn của P1b.
- P3 'close < hỗ trợ': không thể xảy ra, vì ticker_sr_levels tính hỗ trợ là mốc DƯỚI giá hiện tại.
- Cột de_fy/ocf_fy ở updater: thêm vào _has_new_cols sẽ refetch toàn bộ. Chuyển sang pha 2 cùng khối cực trị theo sự kiện, chờ user chốt.
- Tầng F cho mã ĐANG GIỮ: số năm sẽ lặp mỗi ngày. F chỉ áp cho lệnh MỚI (≤1 ngày).

Phạm vi PR: 1 guard mới (chuỗi 54 → 55), không đổi schema dữ liệu, không đổi vnstock_telegram ngoài việc chuyển _fmt_price sang canon.

Phát hiện ngoài phạm vi, đã mở thẻ task_3b872260: lý do ở dòng 📌 EIB trích 'Ngân hàng -2,783 tỷ', trong khi số đó không gồm EIB. Thẻ task_81237dc7 sau PR này chỉ còn phần '… - 1,000 VND' và _to_number('1,000') = 1.0.

Gốc repo: /home/user/vnstock-dashboard.


## Luật

- R1 CHẾ ĐỘ. Hàm `_risk_today_enabled(brief_type)` trong vnstock_brief.py đọc env VNSTOCK_BRIEF_RISK_TODAY (mặc định '1'; '0'/'false'/'no'/'off' là tắt). Brief_type ∉ {morning, afternoon} thì luôn False. collect_context ghi kết quả vào ctx['risk_today'] ngay lúc khởi tạo ctx. MỌI guard chỉ đọc `ctx.get('risk_today') is True`, không đọc os.environ. ctx thiếu khoá (test cũ, pack cũ) hoặc giá trị False thì đi nhánh cũ, giống từng byte.
- R2 CHỦ SỞ HỮU CON SỐ. Mọi dòng có chữ số trong mục '⚠️ Rủi ro cần lưu ý' do hàm thuần `_risk_today_lines(ctx)` (vnstock_brief_guards_sections.py) dựng. Prompt (khối 'Dữ kiện rủi ro hôm nay') và guard gọi CÙNG hàm này. Model được thêm tối đa 1 dòng KHÔNG có chữ số nào. Mọi lý do 12/06 giữ nguyên: model không bao giờ tự viết D/E, Op.CF, đòn bẩy hay superlative. Hàm đặt ở sections chứ không ở canon vì canon phải giữ stdlib-only, trong khi hàm cần _exdate_map, corp_ratio và vnstock_sectors. Canon chỉ chứa hằng số.
- R3 PHƠI NHIỄM (`_risk_exposure(ctx)`), chỉ đọc ctx. held = mã trong ctx['portfolio']. recs = ctx['open_recs']: các lệnh ĐANG HIỆN ở footer Telegram, tức phần emitted của split_recs_by_validation(open_recommendations()) gọi KHÔNG truyền ctx, giống hệt _open_recs_block. movers⭐ = mã trong vn30_gainers/losers có Mã ∈ VN30_TICKERS hoặc GTGD TB ≥ _WATCHLIST_GTGD_MIN_TY. known = Mã của ctx['tickers'] ∪ khoá vn30_fundamentals ∪ held ∪ recs. sectors = với mỗi mã phơi nhiễm, lấy custom_sector_for(t) và cả 'Ngành' gốc; thêm 'tài chính' nếu có mã thuộc financial_tickers ∪ _FINANCIAL_TICKERS, thêm 'bất động sản' nếu có mã thuộc realestate_tickers.
- R4 TẦNG P (chạm mã đang giữ). Trọng số w_t = qty×last_close / Σ, chỉ tính mã có last_close.
  (P1 'concentration_flow') Điều kiện: ≥2 vị thế, VÀ một cụm chiếm ≥ _RISK_CLUSTER_SHARE = 0.50 giá trị, VÀ dòng tiền ngoại bất lợi. Cụm xác định theo thứ tự: tài chính (financial_tickers ∪ _FINANCIAL_TICKERS) → bất động sản (realestate_tickers) → custom_sector_for(t) → Ngành gốc. 'Ngành dòng tiền' của cụm = các dòng ctx['sectors'] có tên chứa từ khoá của cụm ('ngân hàng', 'chứng khoán', 'bảo hiểm', 'tài chính' cho cụm tài chính) ∪ custom group của mã đang giữ trong cụm (vd 'Họ M'). Dòng tiền bất lợi khi: (có ngành dòng tiền nằm trong top-_RISK_SECTOR_TOP_SELL = 3 ngành NN 1T âm nhất VÀ Σ NN 1T của ngành dòng tiền < 0) HOẶC Σ ≤ _RISK_CLUSTER_NN_SELL_TY = −500 tỷ. Dòng in chỉ NÊU TÊN các ngành top-3 kèm số của CHÍNH ngành đó; thêm 'mạnh nhất thị trường' nếu ngành đó là ngành âm nhất. Phụ: một mover cùng Ngành GỐC với một mã đang giữ, có Giá 1T % ≤ _RISK_PEER_WEEK_PCT = −5, chọn mã âm nhất.
  (P2/P3 'held_move', mỗi mã một dòng) Bắn khi gặp một trong: NN 1T của chính mã ≤ −50 tỷ; Giá 1T % ≤ −7; chg_1d_pct ≤ −3 (chỉ khi bar cuối trùng ctx['date']); ngành dòng tiền của mã nằm trong top-3 bán (chỉ khi mã không được P1 phủ).
  (P4 'exdate_held') GDKHQ của mã đang giữ trong 3 ngày.
  Thứ tự: (−w, −severity, mã). Trần P = 2.
- R5 TẦNG M (toàn thị trường, chỉ khi có biến cố trong kỳ).
  (M3 'fx_rate') Lấy từ ctx['macro'], chỉ dòng có as_of ≥ ctx['date'] − 5 ngày. Bắn khi: usdvnd change.pct ≥ +0.30, HOẶC interbank_on change.delta ≥ +1.00 điểm %, HOẶC govt_bond_yield_10y change.delta ≥ +0.15. Gauge chỉ có MỨC (VN10Y−US10Y, LNH−điều hành, 10Y−2Y) KHÔNG BAO GIỜ được in ở đây; chúng thuộc 🌐.
  (M4 'foreign_1d') Tín hiệu 'NN ròng 1D' trong market_sentiment ≤ −1,000 tỷ, VÀ P1 không bắn.
  Không có M1/M2: tình trạng hồi/phân phối thuộc TLDR, Tổng kết và 🔭 Ngắn hạn (P1b). Trần M = 2.
- R6 TẦNG R (GDKHQ chạm lệnh mở). Mã thuộc recs nhưng không thuộc held. Sự kiện lấy qua `_exdate_map({**ctx, 'today': ctx.get('today') or ctx['date']}, _RISK_EXDATE_DAYS=3)`: neo theo ngày phiên, không theo đồng hồ máy, và đã bỏ sự kiện ĐHĐCĐ/lấy ý kiến (vết PNJ). Quy đổi giá: `vnstock_corp_ratio.adjusted_price(entry*1000, titles)/1000`, vì sổ lưu giá theo NGHÌN còn hàm nhận ĐỒNG. Trả None thì ghi 'giá tham chiếu tự điều chỉnh', không kèm số. Bỏ mã đã có '⚠️ GDKHQ' trên một dòng NGOÀI mục Rủi ro (do enforce_exdate_levels gắn trong 💡/watchlist). Phép lọc này dựa trên chữ, nên chỉ chạy trong guard. Thứ tự: (ngày tới sự kiện, mã). Trần R = 2. P4 dùng cùng công thức, nhưng giá gốc là last_close×1000.
- R7 TẦNG F (cơ bản cho LỆNH MỚI). Chỉ xét rec có age_days ≤ _RISK_NEW_REC_DAYS = 1; age_days tính bằng ctx['date'] − ngày created_at. Mã phải PHI TÀI CHÍNH (không thuộc financial_tickers ∪ _FINANCIAL_TICKERS, theo vết MBB) và KHÔNG đang giữ. Ngưỡng: D/E ≥ 1.50 hoặc Op.CF < 0, lấy từ ctx['vn30_fundamentals']. Tối đa 1 dòng, chọn D/E lớn nhất, nếu không có thì Op.CF âm nhất. Nhãn '(BCTC gần nhất)': không ghi 'năm' vì _best_ratio_row có thể chọn hàng TTM. Mã BĐS có Op.CF âm thì PHẢI kèm 'chủ yếu do tích lũy quỹ đất/hàng tồn kho dự án — vốn lưu động, KHÔNG phải lỗ HĐKD; soi thêm D/E và nợ vay'. CẤM chữ 'cao nhất'. Mã đang giữ không có dòng F, vì số năm sẽ lặp mỗi ngày và đã có ở tab cơ bản.
- R8 MẪU DÒNG, TIỀN TỐ, TRẦN.
  Mỗi dòng có dạng '- <tiền tố>…: <dữ kiện có số>. Theo dõi: <điều kiện>.'
  Tiền tố cố định (hằng _RISK_LINE_PREFIXES trong canon): '- Danh mục tập trung', '- Mã đang giữ', '- GDKHQ chạm', '- Tiền tệ xấu đi', '- Khối ngoại bán ròng mạnh', '- Cơ bản lệnh mới', '- Không có rủi ro mới'.
  Thứ tự tầng P → M → R → F, rồi tới dòng model. Tổng tối đa _RISK_MAX_LINES = 4; dòng model chỉ được vào khi còn chỗ.
  Mục rỗng thì in '- Không có rủi ro mới chạm danh mục hay lệnh đang mở trong phiên này.' Không bao giờ để trống.
  Dòng code dùng giá đơn vị NGHÌN như 📌 ({:,.2f}). Giá lệnh định dạng y hệt footer qua canon._fmt_rec_price. Giá quy đổi in tối đa 2 số lẻ, bỏ số 0 thừa (52.0 → '52', 23.5 → '23.5').
- R9 DÒNG CỦA MODEL (`_risk_agent_line_ok`). GIỮ một dòng chỉ khi thoả TẤT CẢ:
  - không rỗng, không mang tiền tố code;
  - không chứa chữ số;
  - không chứa từ khoá trong _RISK_AGENT_DROP_KW = _FUND_KW ∪ {'nợ vay', 'kiệt quệ', 'margin', 'ký quỹ', 'roe'}; _FUND_KW = 'd/e', 'op.cf', 'lưu chuyển tiền', 'lưu lượng tiền', 'hđkd', 'đòn bẩy', 'quỹ đất';
  - nêu ≥1 mã hoặc ngành phơi nhiễm, hoặc chữ 'danh mục';
  - không nêu mã thuộc known mà nằm ngoài phơi nhiễm.
  Chỉ giữ dòng đầu tiên đạt. Guard cuối còn bỏ dòng đó nếu trùng LOẠI với dòng code đã in:
  - NN ('khối ngoại', 'vốn ngoại', 'bán ròng', 'mua ròng');
  - GDKHQ ('gdkhq', 'quyền', 'cổ tức', 'thưởng');
  - tiền tệ ('tỷ giá', 'usd/vnd', 'lãi suất', 'lnh', 'liên ngân hàng', 'lợi suất', 'tpcp');
  - trùng mã của dòng 'Mã đang giữ'.
- R10 MAP NGÀNH. Gán cụm/nhóm cho mã đang giữ bằng custom_sector_for TRƯỚC, Ngành gốc SAU, khớp cách runner gộp (EIB → 'Họ M', VIC → 'Họ VIN'). Không bao giờ viết câu gán số NN của một ngành cho một mã không nằm trong ngành đó trên bảng ngành. Mẫu đúng: 'vốn ngoại đang rút khỏi nhóm này: Ngân hàng bán ròng -2,783 tỷ (1 tuần)'. Mẫu cấm: 'EIB thuộc Ngân hàng bị bán -2,783 tỷ'. So peer (SSB cùng ngành với EIB) thì dùng Ngành gốc, vì đó là ngành thật của doanh nghiệp.
- R11 TỪ VỰNG CẤM trong dòng code. Lý do: dòng code đi qua ~29 guard đứng sau, và để không dẫm lên 3 khung. Danh sách: '🚨', '💼', '🔭', 'đỉnh 20 phiên', 'MA50', 'MA200', 'band', 'Risk-on', 'Risk-off', 'Trung hạn', 'Ngắn hạn', 'cao nhất', 'momentum', 'tâm lý', 'GTGD', 'thanh khoản', 'đóng cửa', 'so với phiên trước', 'thấp hơn', 'cao hơn', 'vĩ mô', 'kỷ lục', 'bắt buộc', 'BUY', 'entry='. Không mở dòng bằng emoji mục (sẽ thành ranh giới mục). Số theo định dạng EN. Hành động BUY/SELL dịch thành MUA/BÁN. Không in lãi/lỗ % hay hành động GIỮ/GIẢM: hai thứ đó thuộc 📌.
- R12 GUARD CŨ.
  - enforce_risk_section (#8) có nhánh MỚI chạy khi risk_today=True, qua helper private `_risk_section_filter`: tìm dòng tiêu đề (section start chứa 'rủi ro cần lưu ý'); bỏ dòng mang tiền tố code và dòng trống; giữ ≤1 dòng model theo R9. KHÔNG nối khối top-N toàn vũ trụ. Thân nhánh cũ giữ nguyên chữ, chỉ thay tuple _fund_kw cục bộ bằng hằng canon._FUND_KW có cùng nội dung.
  - enforce_risk_numbers (#18), áp ở CẢ HAI chế độ: vòng 'missing' bỏ qua dòng không có _FUND_KW, để không còn dán '(Số liệu: EIB D/E=…)' vô nghĩa với ngân hàng. Nhánh cũ không đổi output, vì sau #8 cũ mọi dòng nhắc mã cơ bản đều có từ khoá. Phần (b), (c), (d) tự bản chất đã chỉ chạm dòng có 'D/E=' hoặc 'cao nhất'.
  - enforce_realestate_ocf_context (#9): không đổi.
- R13 GUARD MỚI `enforce_risk_today` (sections), nối NGAY SAU enforce_reference_band_wording. Lúc đó watchlist, 💡 và dấu ⚠️ GDKHQ đã chốt; NN guard đã chạy xong; phía sau còn caveat/GTGD/số/format. Chế độ cũ: no-op. Các bước:
  (a) items = _risk_today_items(ctx), lọc R6 theo text, áp trần;
  (b) thân mục = dòng code + dòng model còn lại (lọc lại bằng R9 để idempotent), hoặc dòng fallback;
  (c) thiếu mục mà có dòng code thì chèn tiêu đề '## ⚠️ Rủi ro cần lưu ý' (brief sáng: '… (phiên chiều)') trước mục 📅/'sự kiện sắp tới', không có thì trước 🌐, không có nữa thì cuối bài. Thiếu mục và không có dòng code: no-op;
  (d) chạy hai lần toàn chuỗi phải ra giống từng byte. Lý do: lượt 2 thì #8 gỡ dòng code theo tiền tố, guard cuối dựng lại y hệt.
- R14 PROMPT (chỉ chế độ mới).
  - `_swap_risk_rules(tmpl)` thay ĐÚNG khối dòng giữa '## ⚠️ Rủi ro cần lưu ý' và '## ' kế tiếp của _MORNING_TEMPLATE / _AFTERNOON_TEMPLATE bằng hằng canon._RISK_TODAY_RULES. Hằng này không chứa dấu ngoặc nhọn, vì template còn .format. Hai hằng template giữ nguyên chữ, nên các test ghim chữ không đổi.
  - build_prompt chèn `_risk_today_block(ctx)` ngay sau _portfolio_block. Tiêu đề khối: '## Dữ kiện rủi ro hôm nay — hệ thống tự in vào mục Rủi ro (KHÔNG chép lại)'; thân là các dòng _risk_today_lines(ctx), hoặc '- (không có rủi ro chạm danh mục/lệnh mở hôm nay)'.
  - `_vn30_fund_block(…, risk_today=True)` đổi header '(cập nhật X)' thành '(số BCTC gần nhất; lấy X)'. Dòng '→ DÙNG các chỉ số này khi nhận xét rủi ro…' đổi thành '→ Bảng tham khảo — mục Rủi ro KHÔNG dùng bảng này (hệ thống tự in số cơ bản của lệnh mới khi cần); KHÔNG bịa số tài chính khác'.
  - build_prompt không có I/O mới.
- R15 UNIVERSE.
  - Chế độ mới: `_fund_universe` (dùng cho fundamentals và load_upcoming) = VN30 ∪ mover_universe ∪ held ∪ recs. Vì vậy HDA/AAA (kém thanh khoản) cũng có sự kiện và số cơ bản. ctx['vn30_fundamentals'] vẫn là đủ vũ trụ, nên scan_ocf_scale và các guard phòng thủ không đổi.
  - Cache sự kiện: `_events_universe(…, extra_tickers=None)`. _maybe_refresh_events truyền `_exposure_tickers()` (mã trong portfolio.json ∪ mã lệnh mở; best-effort, đọc DB chỉ khi file đã tồn tại) ở MỌI chế độ. Việc này vô hại với nhánh cũ vì load_upcoming lọc theo _fund_universe. Ngân sách 120s và backoff 90′ vẫn chặn trên.
- R16 KHÔNG DẪM 3 KHUNG. Mục Rủi ro không đọc _meta/horizon_state.json và không in 🚨, trung hạn/ngắn hạn, MA50/MA200, band/💼, chữ 'Risk-off'. Những thứ đó thuộc header/🔭/📌 của P1b. Khi P1b thêm MA50 vào 📌, gộp vào lượt enrich `_attach_portfolio_levels` để khỏi đọc kho hai lần.
- R17 ĐẾM, KHÔNG ĐOÁN. Sổ brief_watch có loại sự kiện mới 'risk_section' {digest = sha1 thân mục [:12], n_lines, codes}, chỉ ghi khi text có mục Rủi ro. summarize trả risk_pairs / risk_repeats; n_days và enough cũ CHỈ đếm ocf_scale/flow_claim, để badge cũ không đổi nghĩa. Badge doctor: dưới MIN_SAMPLES cặp phiên thì 'ok n=…'; đủ mẫu và tỷ lệ trùng ≥ _RISK_REPEAT_WARN = 0.5 thì warn. Mọi ngưỡng ở R4–R7 là hằng có tên trong canon, và chỉ chỉnh sau khi có số đếm.
- R18 ✅ ĐÃ LÀM 06/10 ở nhánh `claude/vibrant-maxwell-4g4edj` (thẻ task_81237dc7, kèm luôn phần '… - 1,000 VND' và _to_number — CLAUDE-NOTES U73); bước code 1 và các test corp_ratio bên dưới đã có, bỏ qua khi làm PR này. SỬA corp_ratio (cần cho ví dụ golden). parse_event coi là sự kiện cổ phiếu khi `'cổ phiếu thưởng' in unicodedata.normalize('NFC', str(title)).lower()`. So khớp CÓ DẤU vì _norm bỏ dấu sẽ làm 'thưởng' trùng 'thường' (cổ phiếu phổ thông), và 'Niêm yết bổ sung cổ phiếu thường, tỷ lệ 5%' không được đọc thành thưởng. KHÔNG thêm 'co phieu thuong' vào _STOCK_WORDS. Phần '… - 1,000 VND' và _to_number('1,000') để lại cho thẻ task_81237dc7.

## Ví dụ cho brief 05/10

```
⚠️ Rủi ro cần lưu ý
- Danh mục tập trung 100% vào nhóm tài chính: SSI 55% · EIB 45% giá trị đang giữ (theo giá hiện tại); vốn ngoại đang rút khỏi nhóm này: Ngân hàng bán ròng -2,783 tỷ (1 tuần), mạnh nhất thị trường; SSB cùng ngành Ngân hàng với EIB giảm 7.4% sau 5 phiên. Theo dõi: khối ngoại còn bán ròng nhóm Ngân hàng ở phiên kế tiếp.
- GDKHQ chạm lệnh mở GMD (MUA @78): Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0% ngày 2026-10-07; mốc @78 tương đương ≈52 sau quy đổi quyền, entry/TP/SL trong sổ CHƯA quy đổi. Theo dõi: phiên 2026-10-07 giá về quanh mức quy đổi là điều chỉnh cơ học, không phải tín hiệu chạm SL.

Giải thích (phần này không in ra brief)

Dòng 1 (P1):
- Tỷ trọng tính từ 📌: SSI 20,000 × 19.65 = 393,000 nghìn đ; EIB 20,000 × 16.40 = 328,000 nghìn đ; tổng 721,000. SSI chiếm 54.5% (in 55%), EIB 45.5% (in 45%). Cả hai thuộc tài chính nên cụm chiếm 100%.
- Trigger: Ngân hàng là ngành NN 1T âm nhất trong ctx['sectors'] (-2,783), và Σ NN của ngành dòng tiền thuộc cụm (Ngân hàng, Chứng khoán, Bảo hiểm, Họ M) < 0.
- Câu chữ KHÔNG gán -2,783 cho EIB, vì EIB thuộc 'Họ M' và runner gộp ngành theo nhóm tuỳ biến trước.
- Peer: SSB có Ngành gốc Ngân hàng giống EIB, Giá 1T % -7.4 ≤ -5.
- Vế 'Theo dõi': sandbox không có giá nên dùng câu dự phòng. Trên 🖥️ DESKTOP có kho, nếu ticker_sr_levels tìm được mốc thì vế này thành 'Theo dõi: SSI thủng <hỗ trợ pivot> · EIB thủng <hỗ trợ pivot> (hỗ trợ pivot 60 phiên)'.

Dòng 2 (R):
- GMD BUY @78 nằm trong footer khuyến nghị đang mở. Sự kiện thưởng 50% ngày 07/10 cách ngày phiên 05/10 hai ngày.
- adjusted_price(78,000; ['…Cổ phiếu thưởng tỉ lệ 50.0%']) = 52,000 đ, in '≈52'.
- Số này cần bản sửa corp_ratio (R18). Chưa sửa thì dòng in '…; giá tham chiếu tự điều chỉnh, entry/TP/SL trong sổ CHƯA quy đổi', không kèm số.
- Bản 05/10 không có chỗ nào nối hai thông tin này, vì footer dựng ngoài chuỗi guard.

Những gì biến mất so với 05/10:
- 'Đòn bẩy cao nhất VTZ/VJC/PET', 'Op.CF thấp nhất KBC/NVL' và dòng '(Lưu ý BĐS)': không mã nào thuộc 📌 (EIB, SSI), lệnh mở (16 mã) hay watchlist⭐ (SSB, DCM, VPI). Số lại là BCTC năm, đứng yên tới 2027.
- '- Vốn ngoại: VN10Y−US10Y = -0.75…': dòng có chữ số, lại là gauge MỨC (chỉ đổi +0.04 so với -0.79 ngày 02/10; US10Y as_of 01/10). Gauge này đã có ở 🌐.
- '- Tin ngành: EVN…': không chạm mã hay ngành phơi nhiễm nào. Tin vẫn ở 📰.
- KDH và MWG có GDKHQ 07/10 nhưng không thuộc danh mục hay lệnh mở, nên chỉ nằm ở 📅.
- Không có dòng tiền tệ: USD/VND +0.03% dưới ngưỡng 0.30; LNH ON -1.56 là có lợi; 10Y -0.01. Không có dòng khối ngoại 1D: -284 tỷ, trên ngưỡng -1,000.

Dòng chỉ xuất hiện khi kho trên 🖥️ DESKTOP thoả điều kiện (sandbox không có số nên ví dụ không bịa):
(a) '- Mã đang giữ EIB: …' khi NN 1T của chính EIB ≤ -50 tỷ, Giá 1T % ≤ -7, hoặc giảm ≥3% trong phiên.
(b) '- Cơ bản lệnh mới <mã> (MUA @x, mở trong 1 ngày qua): D/E=… (BCTC gần nhất)' khi một trong DRI, BFC, DGW, HDA, DXP (lệnh ngày 0) là mã phi tài chính có D/E ≥ 1.50 hoặc Op.CF < 0.
Trần 4 dòng. Ngày mai mục chỉ lặp nếu biến cố còn: NN còn bán, GMD chưa qua 07/10.

Kill-switch VNSTOCK_BRIEF_RISK_TODAY=0: mục ra y hệt brief 05/10 (2 dòng vĩ mô/tin + 3 dòng cực trị). Có test golden canh.

Ngoài phạm vi nhưng ghi nhận: brief 05/10 mâu thuẫn thiết kế 3 khung ở ba chỗ, đều để P1b xử; mục này cố ý không lặp 🚨.
- 🚨 mức 1 đang BẬT theo §3.7 (94.6% neo 1,853.08, mới 3 phiên) mà brief im lặng.
- Header còn 'Bear — Risk-off'.
- Có 3 lệnh MUA (DRI, BFC, DGW) trong khi trung hạn GIẢM từ 02/10.
```


## Các bước code

- 0. Tạo nhánh feature từ main trong /home/user/vnstock-dashboard. Đọc docs/CLAUDE-NOTES.md, các mục 10/06 (BĐS Op.CF), 12/06 (canonical hoá) và U54 (dòng ~8669), trước khi sửa.
- 1. /home/user/vnstock-dashboard/vnstock_corp_ratio.py:parse_event. Thêm `is_stock = is_stock or 'cổ phiếu thưởng' in unicodedata.normalize('NFC', str(title or '')).lower()`, đặt TRƯỚC nhánh `if is_cash and not is_stock`. Không đụng _STOCK_WORDS và _to_number. Thêm 1 dòng docstring về bẫy 'thưởng'/'thường' khi bỏ dấu.
- 2. /home/user/vnstock-dashboard/vnstock_brief_canon.py (giữ stdlib-only).
  Hằng số: _FUND_KW (tuple 7 từ khoá như #8 cũ), _RISK_AGENT_DROP_KW, _RISK_LINE_PREFIXES, _RISK_FALLBACK_LINE, _RISK_TODAY_RULES, _RISK_MAX_LINES=4, _RISK_TIER_CAPS={'P':2,'M':2,'R':2,'F':1}, _RISK_CLUSTER_SHARE=0.50, _RISK_SECTOR_TOP_SELL=3, _RISK_CLUSTER_NN_SELL_TY=-500.0, _RISK_TICKER_NN_SELL_TY=-50.0, _RISK_HELD_SHOCK_1D_PCT=-3.0, _RISK_HELD_WEEK_PCT=-7.0, _RISK_PEER_WEEK_PCT=-5.0, _RISK_EXDATE_DAYS=3, _RISK_FX_PCT=0.30, _RISK_ON_DELTA=1.00, _RISK_10Y_DELTA=0.15, _RISK_MACRO_MAX_AGE_DAYS=5, _RISK_NN_1D_HEAVY_TY=-1000.0, _RISK_FUND_DE_MIN=1.5, _RISK_NEW_REC_DAYS=1, _RISK_REPEAT_WARN=0.5.
  Hàm: `_fmt_rec_price(p)` (thân y hệt vnstock_telegram._fmt_price) và `_fmt_adj_price(p)` (f'{p:,.2f}' bỏ số 0 thừa và dấu chấm thừa).
- 3. /home/user/vnstock-dashboard/vnstock_telegram.py:_fmt_price. Thân đổi thành `from vnstock_brief_canon import _fmt_rec_price; return _fmt_rec_price(p)`, giữ nguyên tên và docstring. Footer ra y hệt.
- 4. /home/user/vnstock-dashboard/vnstock_brief_guards_sections.py. Thêm các helper private; hàm nào cũng dưới 50 dòng:
  - `_risk_exposure(ctx) -> dict` theo R3.
  - `_risk_weights(ctx)`: trọng số w_t.
  - `_risk_cluster_of(t, ctx)`: thứ tự tài chính → BĐS → custom_sector_for → Ngành gốc; import lười vnstock_sectors.
  - `_risk_held_items(ctx, exp)`: P1, P2/P3, P4.
  - `_risk_market_items(ctx)`: M3, M4.
  - `_risk_exdate_items(ctx, exp, tier)`: R và P4. Dùng _exdate_map với ctx đã cắm 'today'=ctx['date']; quy đổi qua _adjusted_from_thousand(px, titles) = adjusted_price(px*1000, titles)/1000.
  - `_risk_fund_items(ctx, exp)`: F.
  - `_risk_today_items(ctx) -> list[dict]`: mỗi item {tier, kind, tickers, weight, severity, text}. Hàm thuần, không I/O.
  - `_risk_today_lines(ctx, text=None) -> list[str]`: sắp xếp theo R8 và áp trần. Khi có text thì bỏ item R/P4 của mã đã có '⚠️ GDKHQ' trên một dòng ngoài mục Rủi ro.
  - `_risk_agent_line_ok(line, ctx, exp) -> bool` theo R9.
  - `_risk_section_bounds(lines) -> (start, end)`: chỉ nhận dòng tiêu đề đạt _is_section_start và chứa 'rủi ro cần lưu ý'.
- 5. Cùng file, sửa `enforce_risk_section`. Dòng đầu thân hàm: `if (ctx or {}).get('risk_today') is True: return _risk_section_filter(text, ctx)`. Helper private mới `_risk_section_filter`: bỏ dòng mang tiền tố code và dòng trống, giữ ≤1 dòng model theo R9; thân không đổi thì trả NGUYÊN text. Nhánh cũ giữ nguyên chữ, chỉ thay `_fund_kw` cục bộ bằng `_FUND_KW` import từ canon.
- 6. Cùng file, thêm guard công khai `enforce_risk_today(text, ctx)` theo R13. Docstring nêu: vì sao đặt sau enforce_reference_band_wording; bất biến idempotent nhờ tiền tố; nhánh cũ là no-op.
- 7. /home/user/vnstock-dashboard/vnstock_brief_guards_numbers.py:enforce_risk_numbers. Import _FUND_KW từ canon. Đầu vòng `for line in lines[start + 1:end]` của phần 'missing' thêm `if not any(k in line.lower() for k in _FUND_KW): continue`. Docstring ghi rõ lý do: tránh dán '(Số liệu: EIB D/E=…)' cho ngân hàng.
- 8. /home/user/vnstock-dashboard/vnstock_brief_guards.py.
  - Import enforce_risk_today cùng các helper private mới (_risk_exposure, _risk_today_items, _risk_today_lines, _risk_agent_line_ok, _risk_section_filter, _risk_section_bounds, _risk_weights, _risk_cluster_of, _risk_held_items, _risk_market_items, _risk_exdate_items, _risk_fund_items, _adjusted_from_thousand) từ sections để re-export.
  - Trong apply_brief_guards, ngay sau dòng enforce_reference_band_wording, chèn `fixed = enforce_risk_today(fixed, ctx)  # mục Rủi ro theo phơi nhiễm (chế độ mới)`.
  - Docstring module và chuỗi: 54 → 55 guard.
- 9. /home/user/vnstock-dashboard/vnstock_brief.py, phần re-export. Thêm các tên mới vào khối `from vnstock_brief_canon import (…)` (hằng _RISK_*, _FUND_KW, _fmt_rec_price, _fmt_adj_price) và khối `from vnstock_brief_guards import (…)` (enforce_risk_today cùng các helper ở bước 8). tests/test_brief_split.py::test_all_moved_names_are_reexported đòi việc này.
- 10. vnstock_brief.py, các loader mới.
  - `_risk_today_enabled(brief_type) -> bool` đọc VNSTOCK_BRIEF_RISK_TODAY.
  - `_load_open_recs(data_date, opens=None) -> list[dict]`. opens=None thì: nếu `vnstock_memory.DB_PATH` chưa tồn tại thì trả [] (KHÔNG để sqlite tạo DB rỗng, và không ghi vết lỗi); nếu không thì gọi open_recommendations(). Tiếp theo lấy `split_recs_by_validation(opens)[0]` (không truyền ctx) và map mỗi lệnh thành {ticker, action, entry, tp, sl, horizon_days, created_at, age_days}, trong đó age_days = max(0, (date(data_date) − date(created_at)).days).
  - `_attach_portfolio_levels(positions, data_date)`: mỗi mã gọi `vnstock_strategy._load_history_from_parquet(tk, days=90)`. Chỉ khi ngày của time cuối == data_date mới gắn chg_1d_pct (close[-1]/close[-2]−1) và sr_support/sr_resistance (qua ticker_sr_levels với last_close). Mã nào hỏng thì bỏ qua mã đó.
  - `_exposure_tickers() -> list[str]`: mã trong _meta/portfolio.json (theo kill-switch VNSTOCK_BRIEF_PORTFOLIO) ∪ mã của _load_open_recs(today). Best-effort, lỗi trả [].
- 11. vnstock_brief.py:collect_context.
  (a) Thêm `'risk_today': _risk_today_enabled(brief_type)` vào dict khởi tạo ctx.
  (b) CHUYỂN khối 8d (load_portfolio_positions, tên vết 'portfolio') lên ngay sau bước 4 (movers), giữ nguyên thân.
  (c) Ngay sau đó, khi ctx['risk_today']: `try: _attach_portfolio_levels(ctx.get('portfolio') or [], _data_date_str) except Exception as _e: _note_loader_error(ctx, 'portfolio_levels', _e)` và `try: if _or := _load_open_recs(_data_date_str): ctx['open_recs'] = _or except Exception as _e: _note_loader_error(ctx, 'open_recs', _e)`.
  (d) Bước 7: khi ctx['risk_today'] thì `_fund_universe |= {p['ticker'] for p in ctx.get('portfolio') or []} | {r['ticker'] for r in ctx.get('open_recs') or []}`, đặt TRƯỚC _load_vn30_fundamentals và load_upcoming.
  Tên vết mới phải duy nhất, ≥4 ký tự (tests/test_loader_breadcrumbs.py).
- 12. vnstock_brief.py:_events_universe. Thêm tham số `extra_tickers=None`, nối vào `uni` trước khi trả `sorted(uni)`. Trong _maybe_refresh_events gọi `refresh_upcoming(tickers=_events_universe(extra_tickers=_exposure_tickers()))`, giữ nguyên các cửa backoff và kill-switch.
- 13. vnstock_brief.py:_vn30_fund_block. Thêm tham số `risk_today: bool = False`. Khi True thì đổi header thành '(số BCTC gần nhất; lấy {updated})' và đổi dòng '→ DÙNG…' theo R14. Khi False thì chữ cũ giữ nguyên từng byte.
- 14. vnstock_brief.py.
  - Hàm mới `_risk_today_block(ctx) -> str` (thuần), dựng khối theo R14 từ _risk_today_lines(ctx).
  - Hàm mới `_swap_risk_rules(tmpl) -> str`: thay đúng một khối, đếm được bằng test.
  - build_prompt: truyền `risk_today=ctx.get('risk_today') is True` vào _vn30_fund_block. Khi chế độ mới thì append _risk_today_block(ctx) ngay sau khối _portfolio_block, và với brief_type morning/afternoon thì `tmpl = _swap_risk_rules(tmpl)` trước `.format(...)`.
  - Không thêm I/O (test_build_prompt_stays_io_free).
- 15. /home/user/vnstock-dashboard/vnstock_brief_watch.py.
  - `scan_risk_repeat(text) -> list`: trả [] khi không có mục Rủi ro. Có mục thì trả 1 event {'kind': 'risk_section', 'digest': sha1('\n'.join(dòng thân đã strip, bỏ rỗng))[:12], 'n_lines', 'codes': [tiền tố code có mặt]}. Lấy thân mục bằng vnstock_brief_guards_common.brief_section(text, 'Rủi ro') hoặc phép cắt tương đương.
  - observe_brief cộng thêm event này.
  - summarize: n_days/enough cũ chỉ đếm kind ∈ {ocf_scale, flow_claim}. Thêm risk_pairs (số cặp ngày liên tiếp có risk_section, mỗi ngày lấy bản cuối) và risk_repeats (số cặp có digest trùng).
- 16. /home/user/vnstock-dashboard/vnstock_doctor.py:check_brief_watch.
  - Trước nhánh 'chưa nhặt được nghi ngờ nào', tính phần Rủi ro.
  - risk_pairs ≥ MIN_SAMPLES và risk_repeats/risk_pairs ≥ _RISK_REPEAT_WARN thì trả warn với lời 'mục Rủi ro trùng y phiên trước k/n — kiểm VNSTOCK_BRIEF_RISK_TODAY trong .env 🖥️ DESKTOP, rồi xem ngưỡng _RISK_* ở vnstock_brief_canon'.
  - Còn lại thì nối ' · Rủi ro trùng phiên trước k/n' vào message ok. Dưới sàn mẫu ghi 'n=…'.
  - Khi không có event risk_section thì message cũ giữ nguyên chữ.
- 17. /home/user/vnstock-dashboard/run.py: thêm 'tests/test_brief_risk_today.py' vào WHITELIST --fast, cạnh 'tests/test_brief_split.py'.
- 18. Viết test, danh sách ở trường tests. Chạy `python run.py test --fast`. Vì đổi template và chuỗi guard (bài học U65), chạy FULL `python run.py test` trước khi push; máy nào cũng được (○).
- 19. Tài liệu.
  - /home/user/vnstock-dashboard/CLAUDE.md: thêm VNSTOCK_BRIEF_RISK_TODAY vào danh sách kill-switch; số guard trong chuỗi = 55 (đếm bằng regex 'fixed = enforce_' trong apply_brief_guards, sửa cả chỗ đang ghi 53/55 cho khớp); 1 dòng bản đồ kiến trúc 'mục Rủi ro = enforce_risk_today (phơi nhiễm danh mục/lệnh mở), khối cực trị cơ bản rời brief ngày'.
  - /home/user/vnstock-dashboard/docs/CLAUDE-NOTES.md: mục mới U73 ghi lý do, những gì giữ từ 12/06, việc đảo U54 kèm câu trả lời của user, bẫy #18 '(Số liệu: EIB…)', EIB ∈ Họ M, M1/M2 bỏ vì trùng 🔭, nghi vấn PLAUSIBLE 'reconcile có chấm SL cơ học sau GDKHQ không' (ĐẾM trước, chưa vá).
  - /home/user/vnstock-dashboard/docs/VIEC-DANG-LAM.md: 🖥️ DESKTOP `git fetch origin <nhánh> && git merge origin/<nhánh>` rồi `python run.py test`; ○ sáng hôm sau /brief-review so _meta/brief_claude_raw.md với brief_claude.md ở mục Rủi ro; ○ trả lời 2 câu hỏi mở; 🖥️ DESKTOP kill-switch nằm trong .env (không đi qua Dropbox).
- 20. Commit theo conventional ('feat(brief): mục Rủi ro theo phơi nhiễm danh mục + GDKHQ lệnh mở'), có dòng attribution theo system-reminder. Push nhánh feature và báo commit cuối, để user đối chiếu `git log --oneline -1` trên 🖥️ DESKTOP.

## Test mới

- tests/test_brief_risk_today.py (MỚI, thêm vào whitelist --fast). Fixture `_ctx_0510()`:
  - date '2026-10-05', brief_type 'afternoon', risk_today True;
  - portfolio: EIB (20000, 20.5, 16.4, -20.0) và SSI (20000, 23.4, 19.65, -16.0);
  - financial_tickers {EIB, SSI, SSB, NAB, HDB}, realestate_tickers {KBC, NVL, KDH};
  - tickers: EIB Ngành 'Ngân hàng' (NN 1T -10, Giá 1T % -2), SSI 'Chứng khoán' (-20, -1), SSB 'Ngân hàng' (Giá 1T % -7.4, GTGD TB 40), GMD;
  - sectors: Ngân hàng -2783, Bán lẻ & Thương mại -1277, Họ VIN -801, Họ M -120, Chứng khoán -90, Bảo hiểm 20, Khai khoáng & Tài nguyên 3249;
  - vn30_losers: SSB, DCM, VPI (⭐);
  - 16 open_recs y như footer, trong đó GMD @78 age 11 và DRI/BFC/DGW/HDA/DXP age 0;
  - upcoming_events: KDH 'Phát hành cổ phiếu - Trả Cổ tức bằng Cổ phiếu tỉ lệ 10.0%', MWG 'Trả cổ tức bằng tiền mặt - Đợt 2 2025 - 1,000 VND', GMD 'Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0%', cùng 2026-10-07;
  - vn30_fundamentals: VTZ 2.81, VJC 2.74, PET 2.41, KBC (de 1.1, ocf -17344), NVL ocf -6145, EIB de 9.0, SSI de 2.0;
  - macro: usdvnd pct +0.03, interbank_on delta -1.56, govt_bond_yield_10y delta -0.01;
  - market_sentiment: NN ròng 1D '-284 tỷ'; bias_floor GIẢM; vnindex_tech như brief.
  RAW_0510 = khối AI của brief 05/10 với tiêu đề '## …'.
- test_new_mode_golden_0510: mục Rủi ro sau apply_brief_guards(RAW_0510, ctx) ra ĐÚNG 2 dòng của ví dụ, giống từng byte. Toàn mục không chứa 'VTZ', 'KBC', 'D/E', 'Op.CF', 'VN10Y', 'KDH', 'MWG', 'EVN'.
- test_legacy_mode_golden_0510: với ctx thiếu khoá risk_today, VÀ với risk_today=False, mục Rủi ro ra ĐÚNG 5 dòng của brief 05/10 thật ('- Vốn ngoại…', '- Tin ngành…', 'Đòn bẩy cao nhất (phi tài chính): VTZ D/E=2.81, VJC D/E=2.74, PET D/E=2.41 — VTZ cao nhất trong nhóm theo dõi.', 'Lưu chuyển tiền HĐKD thấp nhất: KBC Op.CF=-17,344 tỷ (BĐS), NVL Op.CF=-6,145 tỷ (BĐS).', '(Lưu ý: …)').
- test_full_chain_idempotent_both_modes: apply_brief_guards chạy 2 lần cho kết quả giống hệt, ở cả hai chế độ.
- test_roundtrip_variants: dòng code đi qua toàn chuỗi phải nguyên byte và idempotent, kiểm trên 6 ctx biến thể:
  (a) không danh mục;
  (b) giữ 1 mã phi tài chính có NN 1T -80, Giá 1T % -9, chg_1d -3.5, sr_support → ra dòng '- Mã đang giữ';
  (c) lệnh mới BĐS KDH ocf -1234 → dòng F có 'tích lũy quỹ đất';
  (d) mã đang giữ có GDKHQ cổ tức tiền '1.500 đồng/cổ phiếu' ngày 06/10;
  (e) usdvnd +0.45% as_of 05/10 → dòng '- Tiền tệ xấu đi';
  (f) không danh mục, NN 1D '-1,500 tỷ' → dòng '- Khối ngoại bán ròng mạnh'.
- test_chain_position: trong source của apply_brief_guards, enforce_risk_today( đứng sau enforce_exdate_levels( và enforce_reference_band_wording(, và đứng trước enforce_number_format(.
- test_code_lines_forbidden_vocabulary_and_en_numbers: mọi dòng code của 6 biến thể không chứa token nào trong danh sách R11, không mở đầu bằng emoji mục (_is_section_start False), và không có số kiểu VN (regex \d{1,3}(\.\d{3})+,\d).
- test_p1_custom_group_mapping: không dòng nào ghép 'EIB' với '-2,783' trong cùng mệnh đề; câu dùng 'nhóm tài chính'; peer SSB lấy theo Ngành gốc. Khi Σ NN ngành dòng tiền > 0 và không ≤ -500 thì không có P1. Danh mục 1 vị thế thì không có P1, chuyển sang nhánh P2 theo ngành.
- test_p_triggers_are_dynamic: tập trung 100% mà không có ngành nào thuộc top-3 bán và Σ > -500 thì không có dòng. chg_1d khi bar cuối khác ctx['date'] thì không dùng. Sắp xếp theo trọng số, trần P = 2.
- test_r_exdate_units_and_anchor:
  - GMD @78 + thưởng 50% ra '≈52' và 'CHƯA quy đổi'.
  - Lệnh @25 + 'Trả cổ tức bằng tiền, 1.500 đồng/cổ phiếu' ra '≈23.5'. Assert này bắt lỗi quên ×1000.
  - ĐHĐCĐ thì không có dòng; sự kiện 2026-10-12 thì không có dòng.
  - Mã đã có '⚠️ GDKHQ' trong 💡 thì không lặp.
  - Bản title chưa đọc được tỉ lệ thì in 'tự điều chỉnh'.
  - Monkeypatch date.today() sang 2026-10-06 thì output y hệt.
- test_f_new_recs_only_nonfinancial:
  - Lệnh age 0 phi tài chính D/E 2.10 ra 1 dòng 'D/E=2.10 (BCTC gần nhất)'.
  - Lệnh age 5 thì không có.
  - NAB (bank) age 0 với D/E 9 thì không có.
  - Mã đang giữ phi tài chính D/E 3 thì không có dòng F.
  - Không dòng nào chứa 'cao nhất'.
  - enforce_realestate_ocf_context là no-op trên output.
- test_m3_m4_and_level_gauges_never_print: spread VN10Y−US10Y -0.75 không bao giờ thành dòng. as_of cũ hơn 5 ngày thì không có dòng M3. NN 1D -1,500 có P1 thì không có M4.
- test_agent_line_filter: các dòng sau đều bị bỏ: dòng có chữ số; dòng 'đòn bẩy margin'; dòng có 'D/E'; dòng nêu VTZ (known, ngoài phơi nhiễm); dòng tin EVN (không chạm); dòng 'khối ngoại bán ròng nhóm tài chính' khi đã có P1. Dòng 'Danh mục EIB, SSI cùng nhóm, dễ chịu áp lực tin ngành' được giữ, đứng cuối, tối đa 1 dòng.
- test_fallback_and_insert:
  - Không item, không dòng model thì in đúng _RISK_FALLBACK_LINE.
  - Text thiếu mục mà có item thì chèn '## ⚠️ Rủi ro cần lưu ý' trước 📅. Brief sáng chèn '… (phiên chiều)'.
  - Thiếu mục và không có item thì text giữ nguyên.
  - brief_type allocation thì no-op.
- test_morning_parity: brief sáng có '## ⚠️ Rủi ro cần lưu ý (phiên chiều)' thì ra cùng các dòng code như brief chiều.
- test_prompt_new_mode:
  - build_prompt của cả 2 brief_type, với risk_today=True, chứa _RISK_TODAY_RULES và mọi dòng của _risk_today_lines(ctx).
  - Không còn 'CHỈ nêu rủi ro cơ bản bằng mã lấy TỪ dòng'.
  - _swap_risk_rules thay đúng 1 khối mỗi template.
  - Khối cơ bản có '(số BCTC gần nhất; lấy' và không có '(cập nhật'.
  - Thiếu khoá thì prompt giữ chữ cũ.
- test_risk_today_enabled_env: xoá mọi env có TIỀN TỐ 'VNSTOCK_BRIEF_RISK' trước (vì .env máy thật lọt vào pytest).
  - Mặc định True; '0', 'false', 'off' cho False; 'allocation' cho False.
  - Source collect_context chứa "'risk_today': _risk_today_enabled(brief_type)", '_attach_portfolio_levels(' và '_load_open_recs('.
- test_open_recs_match_telegram_footer: monkeypatch vnstock_memory.open_recommendations và kiểm định chiến lược sao cho có lệnh ẩn. Tập mã của _load_open_recs('2026-10-05', opens) phải trùng tập mã mà vnstock_telegram._open_recs_block() in ra. DB_PATH chưa tồn tại thì trả [] và KHÔNG tạo file.
- test_pack_roundtrip_carries_mode: write_pack rồi read_pack (tmp_path) với ctx có risk_today, open_recs, set keys. finalize_brief/apply_brief_guards trên ctx đọc lại phải cho đúng chữ như trên ctx trong bộ nhớ.
- test_risk_numbers_no_bank_leak: enforce_risk_numbers giữ nguyên dòng 'EIB, SSI lỗ nặng giữa lúc NN bán ròng ngân hàng.' (không thêm '(Số liệu:'), kể cả khi funds có EIB/SSI. Dòng 'KBC D/E=8.83' vẫn được sửa về số thật.
- tests/test_corp_ratio.py (bổ sung):
  - 'Phát hành cổ phiếu - Cổ phiếu thưởng tỉ lệ 50.0%' → stock 0.5; bản NFD của nó cũng vậy.
  - adjusted_price(78000, [title]) == 52000.
  - 'Cổ phiếu thưởng tỉ lệ 9.5%' → 0.095.
  - 'Niêm yết bổ sung cổ phiếu thường, tỷ lệ 5%' → None.
- tests/test_events.py (bổ sung): _events_universe(extra_tickers=['HDA', 'AAA'], overview_path=thiếu) == VN30 ∪ {HDA, AAA}. Mặc định không có extra.
- tests/test_brief_watch.py (bổ sung):
  - scan_risk_repeat trả [] khi text không có mục Rủi ro.
  - Hai thân mục giống nhau cho cùng digest.
  - summarize đếm risk_pairs/risk_repeats, và event risk_section KHÔNG làm đổi n_days/enough cũ.
  - Doctor: dưới sàn mẫu thì 'ok' kèm 'n='; đủ mẫu và trùng ≥ 50% thì warn có fix.
- tests/test_telegram (file hiện có của _fmt_price, hoặc thêm vào test_brief_risk_today.py): _fmt_rec_price(p) == vnstock_telegram._fmt_price(p) với p ∈ {0, 0.5, 9.21, 78, 139.4}.
- Lưới có sẵn phải xanh, không sửa:
  - tests/test_brief_split.py: guard mới được nối, định nghĩa đúng 1 lần, mọi tên mới đã re-export, canon vẫn là leaf.
  - tests/test_loader_breadcrumbs.py: tên vết mới duy nhất; sandbox không DB, không portfolio thì không ghi vết.
- Chạy `python run.py test --fast`, rồi FULL `python run.py test` trước khi push (○). Sau merge: 🖥️ DESKTOP chạy FULL lại vì máy thật có kho; ○ đọc brief chiều đầu tiên trên Telegram.

## Test cũ

- tests/test_brief.py: KHÔNG có test nào phải sửa. Lý do: mọi ctx trong file đều thiếu khoá 'risk_today', nên chạy nhánh cũ giống từng byte, và template cũ giữ nguyên chữ vì việc thay luật chỉ làm lúc chạy, bằng _swap_risk_rules. Các test sau giữ nguyên mà vẫn phải xanh, đã soát từng cái:
  - :1921 test_enforce_risk_section_canonicalizes_all_failure_modes, :1954 test_enforce_risk_section_skips_low_de_and_noops: nhánh cũ của #8.
  - :1843, :1862, :1881, :1903, :1969, :1986, :2007, :2031 (8 test enforce_risk_numbers): mọi dòng đầu vào đều có từ khoá D/E, Op.CF hoặc 'lưu chuyển tiền', nên việc giới hạn vòng 'missing' không đổi kết quả.
  - :874 test_both_templates_have_risk_section_and_money_flow_guard_parity, :2947 test_afternoon_risk_only_uses_block_tickers_with_numbers, :2259 test_build_prompt_includes_fundamentals_block: prompt chế độ cũ.
  - :240, :256, :277, :294, :3277 test_vn30_fund_block_*: tham số mặc định risk_today=False, header vẫn là 'cập nhật 2026-06-01'.
  - :298, :315 test_enforce_realestate_ocf_context_*.
  - :1474 test_close_1507_0110_fixes: chỉ gọi enforce_macro.
  - :1774, :1787: ctx không có khoá nên guard mới là no-op.
- tests/test_brief_split.py: không sửa test. Code phải re-export mọi tên mới (bước 8–9), nếu không test_all_moved_names_are_reexported và test_every_guard_is_wired_into_the_chain sẽ đỏ. Lưới không có con số 54 cứng.
- tests/test_events.py: không sửa. test_events_universe_includes_top_liquid_movers vẫn đúng, vì extra_tickers mặc định None (cố ý không đọc portfolio.json bên trong _events_universe, nếu đọc thì máy thật có EIB/SSI sẽ làm đỏ assert '== VN30'). test_maybe_refresh_events_passes_broadened_universe vẫn đúng, vì tập truyền vào là tập lớn hơn chứa VN30. Chỉ BỔ SUNG 1 test extra_tickers.
- tests/test_brief_watch.py: không sửa. test_observe_brief_writes_both_kinds vẫn ra {ocf_scale, flow_claim}, vì _SSI_LINE không có mục Rủi ro nên scan_risk_repeat trả []. TestBadgeNeverCriesTooEarly giữ nguyên chữ 'CHƯA đủ mẫu', vì n_days chỉ đếm ocf/flow. Chỉ BỔ SUNG test mới.
- tests/test_close_2408_review.py và tests/test_brief_exdate_guard.py: không sửa, nhưng phải chạy lại sau bản sửa corp_ratio. Tiêu đề 'Cổ phiếu thưởng tỉ lệ 20.0%' của MSB nay có giá quy đổi '≈ …'. Assert hiện có chỉ đòi chuỗi con '⚠️ GDKHQ 2026-08-26' nên vẫn đạt. Các ca '≈ not in' dùng tiêu đề khác (quyền mua, entry= không có giá) nên không đổi.
- tests/test_corp_ratio.py: chỉ BỔ SUNG case tham số hoá (xem trường tests). Các case cũ ('Thưởng cổ phiếu, tỷ lệ 5:2', 'THUONG CO PHIEU…', quyền mua bị từ chối…) không đổi.
- tests/test_loader_breadcrumbs.py: không sửa. Code phải dùng tên vết mới 'open_recs' và 'portfolio_levels' (duy nhất, ≥4 ký tự). _load_open_recs không được ném lỗi hay tạo DB khi brief_memory.db chưa có, nếu không fixture real_ctx sẽ đỏ trong sandbox.

## Kill-switch

Kill-switch: `VNSTOCK_BRIEF_RISK_TODAY`, mặc định bật (=1). Đặt 0/false/no/off thì tắt.

Cơ chế:
- Biến chỉ được đọc MỘT lần, trong `vnstock_brief._risk_today_enabled(brief_type)` gọi từ collect_context, sau `_ensure_env_loaded()`. Kết quả ghi vào `ctx['risk_today']`.
- Guard KHÔNG đọc env, nên vẫn là hàm thuần (text, ctx).
- Pack v2 mang theo khoá này, nên `run.py brief --from-file`, `/brief-close` và `telegram close --force` tái lập đúng chế độ của lúc xuất pack. ctx thiếu khoá (pack cũ) thì chạy chế độ cũ.

Khi tắt (=0), mọi thứ về nguyên trạng, giống từng byte (có test golden 05/10 canh):
- enforce_risk_section chạy thân cũ và nối `_canonical_risk_lines` (VTZ/VJC/PET, KBC/NVL);
- enforce_risk_today là no-op;
- template sáng/chiều giữ nguyên đoạn luật D/E/Op.CF;
- `_vn30_fund_block` giữ header '(cập nhật …)' và câu '→ DÙNG…';
- không có khối 'Dữ kiện rủi ro hôm nay';
- `_fund_universe` không mở rộng;
- không gọi `_load_open_recs` hay `_attach_portfolio_levels`.

Không đi theo công tắc, vì đúng ở cả hai chế độ:
- (a) enforce_risk_numbers bỏ qua dòng không có từ khoá cơ bản (không đổi output của nhánh cũ);
- (b) bản sửa corp_ratio 'cổ phiếu thưởng';
- (c) `_events_universe(extra_tickers=…)` chỉ làm cache sự kiện có thêm mã, mà load_upcoming ở chế độ cũ vẫn lọc theo universe cũ;
- (d) sổ brief_watch 'risk_section' (tắt chung bằng VNSTOCK_BRIEF_WATCH=0).

Làm ở đâu: đặt trong `.env` của 🖥️ DESKTOP (máy chạy task Daily 18:00). .env KHÔNG đi qua Dropbox, nên chạy brief tay ở 💻 LAPTOP thì phải đặt riêng ở đó. Có hiệu lực từ brief kế tiếp.

Phải thêm tên biến vào danh sách kill-switch trong CLAUDE.md. Test đọc env phải xoá biến theo TIỀN TỐ `VNSTOCK_BRIEF_RISK` trước khi chạy.


## ❓ Câu hỏi cho user (chặn việc code)

1. Bỏ khối cực trị toàn thị trường (VTZ/VJC/PET D/E, KBC/NVL Op.CF) khỏi brief NGÀY là đảo ghi chú U54 ('mục Rủi ro sinh ra để nói KBC'). Anh đồng ý không? Mặc định nếu anh không trả lời: bỏ khỏi brief ngày. Bảng vẫn còn trong prompt và tab cơ bản trên dashboard, và VNSTOCK_BRIEF_RISK_TODAY=0 trả lại như cũ. Nếu anh vẫn muốn nhận bảng qua Telegram, pha 2 sẽ in nó chỉ khi có kỳ BCTC mới (kèm 'kỳ trước …'), hoặc thành tin thứ Bảy đầu tháng. Anh chọn cách nào?
2. 16 lệnh khuyến nghị backtest trong footer (GMD, DRI, BFC, …): anh có vào lệnh thật theo chúng không? Mặc định là CÓ tính chúng là phơi nhiễm, vì footer đẩy tới anh mỗi tối. Nhờ vậy có dòng 'GDKHQ chạm lệnh mở GMD' và dòng cơ bản cho lệnh MỚI. Nếu anh không theo các lệnh này, em sẽ chỉ giữ tầng danh mục đang giữ và tầng thị trường, cho mục ngắn hơn.

## Phụ lục — phát hiện khác về brief 05/10 (đã qua phản biện)

- **[investor/F1] medium** · ⚠️ Rủi ro cần lưu ý (3 dòng Đòn bẩy / Op.CF / Lưu ý BĐS) — Phát hiện đúng về bản chất, nhưng nên hạ xuống mức medium. Đây là khối nhiễu: in vô điều kiện, không ghi kỳ báo cáo và không liên quan danh mục. Số liệu không sai, và việc giữ tín hiệu KBC là cố ý. Cụ thể:  (1) enforce_risk_section luôn nối _canonical_risk_lines(ctx) mỗi khi ctx có vn30_fundamentals. Không có điều kiện nào về mức liên quan hay về chuyện số đã đổi hay chưa. Guard này nằm trong chuỗi chung apply_brief_guards, nên khối xuất hiện cả brief sáng (prompt :257) lẫn brief chiều (:345), tức 2 lần mỗi ngày.  (2) Op.CF đứng yên cả năm. _annual_operating_cf chỉ lấy năm tài chính đã đóng gần nhất (y < năm hiện tại), nên KBC −17,344 / NVL −6,145 là số FY2025 và sẽ không đổi tới khi có BCTC năm 2026. Riêng D/E thì phát hiện nói hơi quá. D/E lấy trước hết từ bảng ratio (_best_ratio_row). Theo comment trong code, bảng này trộn dòng năm với dòng TTM/giữa kỳ, nên D/E có thể nhích theo quý.   
  _Nguồn:_ Xác nhận: vnstock_brief_guards_sections.py:1029-1059 (_canonical_risk_lines) và :1093 (enforce_risk_section nối vô điều kiện, cổng duy nhất ở :1073). Dữ liệu đến từ vnstock_brief.py:1583-1634 (_load_vn30_fundamentals) và :2509-2512. Op.CF được đóng băng theo năm ở vnstock_fundamental_updater.py:363-
- **[investor/F2] medium** · 💡 Đề xuất giao dịch (so với TLDR Stance và 📋 Watchlist) — Phát hiện đúng một phần. Phần "brief tự mâu thuẫn: Stance GIẢM mà vẫn có 3 lệnh MUA" là sai về bản chất. Giữ lệnh backtest kèm cảnh báo, không lọc, là lựa chọn có chủ đích, ghi ở docstring enforce_buy_vs_bias_caveat. THIET-KE-BRIEF-3-KHUNG §3.10 (dòng 489) cũng ghi '💡 Đề xuất giao dịch từ backtest' cố ý neo tín hiệu ngày, và mức "cứng" (dòng 887) chỉ "cảnh báo lệnh MUA". Người đọc cũng không bị bỏ trống cảnh báo. Câu mở mục do LLM viết là "Bias GIẢM nên chỉ giải ngân tỷ trọng nhỏ, đúng cắt lỗ". Ngay trong tin đó còn có _BUY_BIAS_CAVEAT y nguyên ở khối 📋 Khuyến nghị đang mở (vnstock_telegram.py:414-416), và khối này liệt kê đúng DRI/DGW/BFC (ngày 0/20). Câu "caveat không bắn" chỉ đúng cho caveat trong thân mục Đề xuất.  Có hai điểm THẬT: (1) Lỗ guard, biến thể thứ ba sau #17 (29/09) và vá 30/09. LLM viết "DRI: entry 16.6 · TP 19 · SL 15.5 (~4,400 cp)", không có BUY/MUA và không có '='. _R  
  _Nguồn:_ Do LLM: dòng "TK: entry E · TP T · SL S (~N cp)" bỏ BUY, '=' và nhãn "rủi ro 1% NAV", cùng câu "chỉ giải ngân tỷ trọng nhỏ".  Guard bỏ lọt: - vnstock_brief_guards_sections.py:1690-1696 (_REC_RAW_LINE_RE) - vnstock_brief_guards_sections.py:1432-1436 (_is_buy_line trong enforce_buy_vs_bias_caveat :139
- **[investor/F3] medium** · 📋 Watchlist sáng mai (DCM) so với 📋 Khuyến nghị đang mở — Phát hiện có thật, nhưng phải nói lại cho đúng ở ba chỗ.  (1) Hai thông điệp này không trái nhau tuyệt đối. Watchlist chỉ bảo giảm tỷ trọng NẾU giá thủng 32,300. Ngay dưới khối lệnh mở đã có caveat "bối cảnh chung đang GIẢM → … tôn trọng cắt lỗ (SL), cân nhắc giảm tỷ trọng". Lỗi thật là MỘT mã có HAI bộ mốc cắt lỗ: - watchlist cắt ở 32,300, tức chỉ ~0.6% dưới giá 32,500; - lệnh DCM BUY @33 thuộc tầng vị thế 20 phiên, có SL riêng (sổ có, nhưng khối Telegram trong brief không in ra). Người đang giữ DCM theo lệnh phải tự chọn dùng stop nào. Đây đúng là mẫu "hai bộ mốc" đã ghi ở FRT 23/09 (CLAUDE-NOTES:8045) và FRT 29/09 (U64, CLAUDE-NOTES:7524-7572). Hôm nay là lần thứ 3.  (2) Con số "giá dưới entry ~1.5%" không kiểm được. `_fmt_price` (vnstock_telegram.py:343) in giá ≥10 với 0 chữ số thập phân, nên "@33" có thể là entry thật bất kỳ trong khoảng 32.5–33.49. Giá hiện tại vì thế nằm dưới entr  
  _Nguồn:_ Ba lỗ cùng gây ra lỗi: (a) Prompt: vnstock_brief.py:4352 cắt `fresh[:5]`; hướng dẫn watchlist ở vnstock_brief.py:328-330 không có luật đối chiếu với lệnh mở. (b) Thiếu guard: chuỗi apply_brief_guards ở vnstock_brief_guards.py:267 (enforce_watchlist_levels) không có bước nào so watchlist với open_rec
- **[investor/F4] medium** · 🏆 Dẫn dắt & Tụt hậu + 💰 Dòng tiền (đóng góp pp của ngành) — Phần lõi của phát hiện là THẬT. Đóng góp pp của ngành = trọng số vốn hoá của ngành × lợi suất 1 tuần trung bình CỘNG ĐỀU của mọi mã trong ngành. Đóng góp pp của từng mã = trọng số vốn hoá × lợi suất của chính mã đó. Hai cách tính này không cộng khớp với nhau, nên một ngành mà mã lớn nhất tăng mạnh vẫn có thể hiện đóng góp ÂM. Dòng "Khai khoáng & Tài nguyên −0.014pp" đứng cạnh "MSR ≈ +0.103pp" chính là triệu chứng đó, không phải do hai số đo hai khung thời gian khác nhau: cả hai đều là 1 tuần và chung một mẫu số.  Từ số trong brief suy ra: MSR nặng khoảng 0,72% tổng vốn hoá, tức chừng 65% vốn hoá cả ngành (ngành 1,1%). Lợi suất cộng đều của ngành ≈ −1,3%. Tôi dựng lại bằng dữ liệu giả (MSR +14,3%, 9 mã nhỏ −3%) và ra đúng y như brief: ngành −0.014pp, MSR +0.103pp, còn TỔNG đóng góp các mã trong ngành là +0.092pp. Muốn tổng theo vốn hoá ra âm thì phần còn lại của ngành (~0,38%) phải giảm t  
  _Nguồn:_ vnstock_runner.py:716 (Giá 1T % ngành = mean cộng đều) + vnstock_brief.py:2484 (contrib ngành = weight × mean đó; đối chiếu :2469 contrib mã) → _leadlag_candidates :2019 → chọn lead/lag :2493-2500 → khối 🎯 :3054-3070 (ngưỡng 0.05) + _sector_lines :3397-3411 → guard enforce_lead_lag vnstock_brief_gua
- **[investor/F5] medium** · 📋 Khuyến nghị đang mở (khối Telegram) so với 📅 Sự kiện sắp tới — Phát hiện ĐÚNG ở phần lõi, nhưng ba chi tiết phải sửa.  (1) Dòng lệnh GMD trong khối Telegram không có cảnh báo GDKHQ. _open_recs_block được ghép sau apply_brief_guards (push_close_brief, vnstock_telegram.py:686; brief sáng cũng vậy ở dòng 640). Vì vậy nhánh 'khuyến nghị đang mở' trong _zone_of của enforce_exdate_levels không bao giờ chạy, vì thân brief không bao giờ có mục tên đó. Hệ quả: GMD 'BUY @78 → TP/SL %' vẫn được in nguyên, dù chỉ cách GDKHQ thưởng 50% (07/10) hai ngày. Ngày GDKHQ, giá tham chiếu ≈ giá trước đó /1,5 (khoảng 52 nếu giá đang quanh 78). Người theo lệnh sẽ tưởng SL đã thủng.  (2) Đối soát lệnh không biết gì về quyền. reconcile_recommendations / _grade_rec không nối với sự kiện quyền, và emit_recommendations cũng vậy. Nhưng con số 'lỗ khoảng 33%' là SAI. _grade_rec thoát lệnh tại giá SL đã lưu (return sl, "sl"), nên pnl_pct ghi vào sổ = %SL của lệnh (cỡ −5…−8%), khôn  
  _Nguồn:_ - vnstock_telegram.py:359-418 (_open_recs_block: không gắn GDKHQ, không có giá hiện tại) và vnstock_telegram.py:341-356 (_fmt_price: ngưỡng 10, đã trôi khỏi vnstock_brief.py:4123-4147 _fmt_rec_price). - Ghép sau guard ở vnstock_telegram.py:681-689 (close) và 640 (morning). Nhánh chết ở vnstock_brief
- **[investor/F6] low** · Header ⚖️ Regime so với 📊 Tổng kết phiên — Phát hiện có thật nhưng nhẹ hơn mô tả, và phần "sống qua P1b" bị nói quá.  Cùng một tin có hai "Regime" và hai "conviction". Đó là hai thước đo khác nhau, mỗi con số đúng theo định nghĩa riêng của nó, và cả hai đều chỉ chiều GIẢM. Hai bên chỉ khác cường độ và thang đo, không trái chiều nhau. (a) Header lấy từ vnstock_regime: 7 phiếu kỹ thuật VNINDEX, score -5 ≤ -4 nên ra nhãn "❄️ Bear — Risk-off". "conviction 71%" ở đây là |score|/n = 5/7, tức độ đồng thuận của các phiếu. (b) Thân bài lấy từ vnstock_market_analyzer.market_regime, tính trên composite của 31 ngành: 3 ngành tích cực, 8 ngành tiêu cực, nên diff_ratio = -5/31 = -0.16. Số này nằm trong khoảng (-0.3, -0.1), nên ra nhãn "📉 Slight bearish bias", AI dịch thành "nghiêng giảm nhẹ". "conviction -0.03" thực ra là TRUNG BÌNH composite các ngành. Con số này gần trung tính và đo theo thang khác hẳn, không phải độ tin cậy.  Brief KHÔNG gh  
  _Nguồn:_ - Header: vnstock_telegram.py:255-280 (_regime_block; :262 tính conv, :273 in dòng), số liệu từ vnstock_regime.py:204 (confidence). - Thân bài: vnstock_brief.py:3136 đưa `conviction=` (= vnstock_market_analyzer.py:618 avg composite ngành; nhãn :589) vào prompt, LLM chép ra mục Tổng kết phiên. - Phụ:
- **[investor/F7] low** · 📌 Danh mục đang giữ — Phát hiện ĐÚNG MỘT PHẦN. Trong bốn ý, hai ý đúng, một ý nói quá và một ý đã được ghi nhận từ trước.  (1) THỨ TỰ MỤC — ĐÚNG. Template chiều đặt 📌 ở vị trí thứ 12/14, ngay sau 🌐/📰/📚 (vnstock_brief.py:359). Template sáng cũng để 📌 ở cuối (:271). Phần chữ đứng trước 📌 dài khoảng 6–7 nghìn ký tự. `_split_for_telegram` cắt mỗi tin ở 4.000 ký tự nên 📌 rơi sang tin Telegram thứ hai. Thiết kế 3 khung (P1b) chỉ thêm 🔭 cùng dòng 💼 ngay sau TLDR, còn mục danh mục vẫn để ở :360 ⇒ đề xuất dời 📌 KHÔNG trùng với thứ tài liệu đã chốt. Lưu ý thêm: skill /brief-close không tự định thứ tự mà làm theo prompt, nên chỉ cần sửa template, cộng thêm chỗ chèn dự phòng của `enforce_portfolio_facts` (hiện chèn trước 💡).  (2) EIB 'GIẢM TỶ TRỌNG' mà không nói bao nhiêu, ở mức nào — ĐÚNG, nhưng ĐÃ BIẾT. Hội đồng chấm 30/09 (U64) đã ghi 'EIB/SSI không mốc' và cố ý hoãn theo luật 'đếm trước khi vá'. Thiết kế §4(C) thêm M  
  _Nguồn:_ - Thứ tự mục: TEMPLATE, vnstock_brief.py:359 (chiều) và :271 (sáng). - Thiếu mốc và lý do yếu: dữ kiện đầu vào nghèo, ở vnstock_brief_canon.py:317 `_portfolio_fact_line` và vnstock_brief.py:1958 `_portfolio_block`. Luật 'ghi thiếu' chỉ có ở .claude/skills/brief-close/SKILL.md:87, không có trong temp
- **[investor/F8] medium** · 📋 Watchlist sáng mai (SSB, DCM, VPI) — Phát hiện chỉ đúng một phần, và quy sai nguồn.  PHẦN ĐÚNG: mốc của DCM và VPI chỉ cách giá vừa sát sàn 0,5%. DCM: thủng 32,300 (−0.62%), hủy 32,700 (+0.62%). VPI: 56,600 (−0.53%), 57,300 (+0.70%). Hai mốc kích hoạt và hủy nằm trong một dải khoảng 1,2–1,3%. Biên độ một phiên bình thường của một mã (DCM vừa −7.7% trong 5 phiên) là quét được cả hai mốc trong cùng ngày, nên setup không còn phân định được gì.  Mốc này KHÔNG do LLM tự chọn, cũng không phải lỗi guard. Nó do tầng data đưa sẵn vào prompt. `ticker_sr_levels` (vnstock_brief.py:2799) gọi `_select_sr_levels` với sàn `_SR_MIN_DIST_PCT = 0.005` (vnstock_brief.py:2786). Sàn này được chỉnh cho VNINDEX: chú thích ghi rõ "VNINDEX daily swing ~1%". Nó được dùng lại nguyên cho từng mã, mà biến động ngày của một mã lớn hơn chỉ số 2–3 lần. Ngoài ra, ứng viên mốc là đỉnh/đáy của BẤT KỲ bar nào trong 60 bar, không phải swing pivot. Vì vậy mốc đư  
  _Nguồn:_ Tầng DATA, không phải LLM hay guard. vnstock_brief.py:2786 (`_SR_MIN_DIST_PCT = 0.005`, chỉnh cho VNINDEX) được `ticker_sr_levels` dùng lại cho từng mã (vnstock_brief.py:2799-2820, ứng viên là mọi đỉnh/đáy bar, chọn qua `_select_sr_levels` :2823-2851). Mốc được gắn ở `_attach_ticker_sr` :2221-2253, 
- ~~[investor/F9] 🔧 Đề xuất bổ sung (+ câu đuôi mục 💡)~~ — BÁC: Gọi đây là "leak" là hiểu sai. Mục 🔧 "Đề xuất bổ sung" được thiết kế cố ý làm kênh báo dữ liệu còn thiếu cho chủ hệ thống. User vừa là nhà đầu tư vừa là người phát triển nên đây không phải chữ nội bộ bị lộ ra. Câu "Cần thêm giá dầu Brent/WTI để lượng hóa tác động tin OPEC+" cũng nói đúng sự thật: pipeline không có giá Brent/WTI, mà tin OPEC+ thì có thật trong mục 📰 của chính brief. Model gắn ví dụ
- **[investor/F10] low** · 📚 Báo cáo vĩ mô & phân bổ — Phát hiện đúng về mặt trình bày, nhưng nói quá ở hai điểm, nên hạ xuống low.  (1) Phần đúng. Mục 📚 in báo cáo HedgeAcademy 10/07 ngang hàng với báo cáo 04/10. Brief có ghi ngày [2026-07-10] nhưng không ghi tuổi hay trọng số. Báo cáo này 87 ngày, trọng số còn w=(90−87)/60=0,05. Dòng "Consensus 2 báo cáo" đếm mọi báo cáo có w>0, nên người đọc thấy "2 báo cáo cùng chiều" trong khi khoảng 95% trọng số nằm ở báo cáo 04/10.  (2) Nói quá thứ nhất: "tưởng có 2 nguồn độc lập" là sai. Cả hai dòng đều ghi rõ "HedgeAcademy", nên brief không hề ngụ ý hai nguồn độc lập.  (3) Nói quá thứ hai: con số và quyết định không bị ảnh hưởng. Cả hai báo cáo đều có CP −1, nên trung bình có trọng số vẫn là −1,00. Nếu bỏ báo cáo 10/07 thì báo cáo 04/10 đứng một mình vẫn có stance −1,00, strength=min(1, 1,0)=1, tilt +1 đủ một band. Band B4, tilt và stance in ra đều đúng theo định nghĩa.  (4) Lỗi tự hết sau 3 ngày: b  
  _Nguồn:_ Dòng báo cáo sinh ở vnstock_brief_canon.py:276-286 trong _macro_reports_body_lines (:254-295), dòng Consensus ở :287-290. Danh sách lấy từ vnstock_brief.py:2600-2605 (load_for_analysis, không lọc theo trọng số; cùng một hàm dựng cả prompt và guard). Guard chép vào brief ở vnstock_brief_guards_sectio
- **[investor/F11] low** · 📰 Tin kinh tế/chính trị nổi bật — Phát hiện này đúng một phần. Lõi thật nằm ở chỗ prompt và guard nói hai điều khác nhau. Template (vnstock_brief.py:265-266 cho morning, :353-354 cho close) dặn LLM chọn "1-3 tin TÁC ĐỘNG MẠNH nhất, kèm hướng và ngành". Nhưng enforce_market_news (vnstock_brief_guards_sections.py:163-197) thay TOÀN BỘ thân mục bằng mọi item trong ctx["market_news"]. ctx này nạp ở vnstock_brief.py:2579 với limit=6. Vậy phần LLM chọn và bình luận bị vứt, chỉ thị "1-3" là chữ chết. Các tin xếp theo ngày giảm dần (vnstock_news_feeds.py:701), không theo độ quan trọng. Cache tin cũng KHÔNG có trường điểm tác động nào để xếp, chỉ có _sentiment và _impact dạng chữ. Điểm 1–5 chỉ có ở sổ riêng của news-alert (news_alert_seen.json). Vì thế 3/6 slot là tin ⚪ trung lập. In 6 tin là cố ý: CLAUDE-NOTES ghi "top 6, ≤3 ngày", và guard đè để chống bịa tiêu đề, nên đây không phải bug dữ liệu.  Hai ý phụ của phát hiện sai hoặ  
  _Nguồn:_ Xác nhận: phần xác định (deterministic) gồm vnstock_brief.py:2579 (limit=6), vnstock_news_feeds.py:698-702 (lọc no-impact + xếp theo ngày), vnstock_brief_guards_sections.py:163-197 (enforce_market_news đè cả mục), vnstock_brief_canon.py:219-242 (định dạng dòng). Chỉ thị "1-3 tin" bị vô hiệu nằm ở vn
- **[investor/F12] low** · 🏆 Dẫn dắt & Tụt hậu / 💰 Dòng tiền (Luân chuyển) — Phát hiện đúng, mức thấp. Cần sửa ba chỗ: nguyên nhân của vế 2, số dòng, và đề xuất sửa vế 2.  (1) Ngưỡng lộ ra brief: đúng. Prompt chép thẳng luật ra: "GHI 'Chưa có nhóm dẫn dắt rõ ràng' (đóng góp +pp lớn nhất chỉ {_lc:+.3f}pp < 0.05)" (vnstock_brief.py:3065; vế tụt hậu có câu tương tự "> -0.05" ở :3069). LLM chép lại thành "dưới ngưỡng 0.05". Câu chuẩn mà guard enforce_lead_lag muốn có (vnstock_brief_guards_sections.py:561) KHÔNG nêu ngưỡng: "Chưa có nhóm dẫn dắt rõ ràng (đóng góp lớn nhất chỉ +0.049pp)". Nhưng guard chỉ viết lại dòng khi dòng đó SAI (dòng thiếu chữ "chưa có"), nên dòng LLM đã đúng ý mà lộ ngưỡng thì vẫn lọt nguyên văn. Hậu quả cho người đọc: thấy 0,049 sát 0,05 thì "không có dẫn dắt" trông như quyết định cắt mép, trong khi brief không nói ngành +0,049pp là ngành nào.  (2) Vụ "giá xanh, tiền thoát" mà nhãn lại là "tích luỹ": KHÔNG phải hai bộ phân loại tình cờ đá nhau.  
  _Nguồn:_ Ngưỡng: prompt vnstock_brief.py:3065 (và :3069) do LLM chép lại; guard vnstock_brief_guards_sections.py:572-578 không viết lại dòng phủ định đã đúng ý. Nhãn mâu thuẫn: mâu thuẫn có sẵn trong prompt vì danh sách cần composite>0 (vnstock_market_analyzer.py:756-757) mà prompt lại gắn _composite_tag (vn
- **[investor/F13] low** · 🌐 Vĩ mô + độ dài toàn brief — Nhìn chung phát hiện đúng (brief dài quá mức, mục Vĩ mô là bảng dữ liệu thô), nhưng ba ý con sai hoặc đề xuất sửa đi ngược mục đích: (1) Độ dài: riêng thân AI Outlook (đã bị rút gọn bằng "..." khi dán) là khoảng 1.185 từ tách theo khoảng trắng, khoảng 7.560 ký tự, tức khoảng 2,4 lần trần "Giới hạn 500 từ" (vnstock_brief.py:369). Cộng header và khối khuyến nghị thì vượt 8.000 ký tự, nên Telegram tách thành khoảng 3 tin (_MAX_MSG_LEN 4000, vnstock_telegram.py:31). Nói "chủ yếu vì khối code" chỉ đúng một nửa: các khối guard dán vào sau trần gồm 🌐 khoảng 234 từ, 📰 khoảng 87, 📚 khoảng 79, 📅 khoảng 69 và dòng D/E/Op.CF canonical khoảng 60, cộng lại khoảng 530 từ (khoảng 45%). Phần LLM viết còn khoảng 650 từ, tự nó đã vượt 500, vì template bắt nộp 14 mục. Trần 500 từ trên thực tế không có tác dụng. (2) Mục Vĩ mô: enforce_macro thay TOÀN BỘ thân mục bằng _macro_body_lines(directive=False), nên c  
  _Nguồn:_ Độ dài và mục Vĩ mô: vnstock_brief_guards_sections.py:84-134 (enforce_macro) thay thân mục bằng vnstock_brief_canon.py:112-158 (_macro_body_lines, directive=False), trái với template vnstock_brief.py:351 ("1-2 dòng") và :369 ("500 từ"). Header 📉 cố định ở vnstock_telegram.py:678. Lặp momentum: heade
- **[investor/F14] low** · 📌 Danh mục (EIB) + 🎯 TLDR — chữ khung thời gian — Cả hai lỗi đều có thật, nhưng chỉ là lỗi chữ: số liệu đúng, nên kind phải là nhãn/diễn đạt chứ không phải "wrong-number".  (1) Nhãn khung bị lặp ở dòng EIB là do guard gây ra. LLM viết "Ngân hàng bị NN bán ròng -2,783 tỷ trong 1 tuần, bias GIẢM". enforce_portfolio_facts giữ nguyên phần sau dấu → mà LLM viết. Sau đó enforce_nn_frame_labels chỉ nhìn 12 ký tự sau "tỷ" (" trong 1 tuầ") nên không thấy chữ "tuần" và gắn thêm " (1 tuần)", ra "-2,783 tỷ (1 tuần) trong 1 tuần". Tôi đã chạy lại guard trên câu dựng lại và ra đúng chuỗi lỗi. Kết quả này idempotent, nên không có bước nào sau đó gỡ được. Cùng cơ chế còn lặp nhãn với "trong một tuần" (15 ký tự) và gắn nhãn thừa trước "trong 5 phiên", ra "(1 tuần) trong 5 phiên". Với " trong tuần" (11 ký tự) và " sau 1 tuần" thì guard vẫn bắt đúng. Test hiện có (test_brief.py:1362-1385) không phủ ca cụm khung đứng SAU số.  (2) "(+0.89% so với đóng cửa h  
  _Nguồn:_ (1) vnstock_brief_guards_sections.py:868, trong _fix: cửa sổ nhìn tới sau số chỉ 12 ký tự; :887 là chỗ tương tự trong _fix_rev. Guard được gọi từ vnstock_brief_guards.py:259. Phần chữ LLM được giữ qua enforce_portfolio_facts (vnstock_brief_guards_sections.py:349-357). (2) Ví dụ trong prompt ở vnstoc
- **[data/F1] medium** · ⚠️ Rủi ro cần lưu ý (khối D/E + Op.CF) — Phát hiện ĐÚNG về bản chất. Ba dòng D/E/Op.CF là khối canon do code dựng, không phải LLM viết. Số không sai, nhưng khối cũ, không ghi kỳ báo cáo, và bị chính guard tách khỏi danh mục. Cần sửa vài điểm cho chính xác:  (1) Op.CF đúng là gần như hằng số. `_annual_operating_cf` lấy năm tài chính đã đóng gần nhất, tức FY2025. KBC −17,344 và NVL −6,145 đã được ghi là "FY2025, số THẬT" từ ngày 10/06 (CLAUDE-NOTES dòng 86-87). Fixture test dùng đúng hai số này, nên chúng đứng yên ít nhất khoảng 4 tháng. Ngày 29/09 notes cũng đã xác nhận TTM của KBC là −16,510, khác số đang in.  (2) D/E KHÔNG hẳn là hằng số. D/E lấy từ dòng mới nhất có giá trị trong bảng ratio của VCI, chạy lại mỗi T7 bằng `fundamentals --force`. Fixture tháng 6 ghi PET 2.67 / VTZ 2.63, hôm nay là PET 2.41 / VTZ 2.81. Con số có trôi, chỉ là thứ hạng ổn định.  (3) Câu "đứng yên tới BCTC năm 2026 (Q1–Q2/2027)" chưa chính xác. Code   
  _Nguồn:_ vnstock_brief_guards_sections.py:1029-1059 (`_canonical_risk_lines`) và :1062-1096 (`enforce_risk_section`; bộ lọc `_is_fundamental` ở :1084-1091 xoá dòng nhắc mã danh mục/watchlist). Được gọi ở vnstock_brief_guards.py:252. Dữ liệu từ vnstock_fundamental_updater.py:363-416 (Op.CF năm lịch đã đóng) v
- **[data/F2] medium** · ⚠️ Rủi ro cần lưu ý (cơ chế guard) — Cơ chế lọc là có thật, nhưng phát hiện gốc nói quá ở 3 chỗ và bỏ sót 1 chỗ.  ĐÚNG: trong enforce_risk_section, hàm _is_fundamental coi một dòng là "cơ bản", rồi XÓA nó, nếu dòng có từ khóa (d/e, op.cf, hđkd, đòn bẩy, quỹ đất…) HOẶC khớp \b<mã>\b với BẤT KỲ mã nào trong ctx["vn30_fundamentals"]. Tập mã này rất rộng. Nó gồm VN30 cộng với mover_universe (mọi mã có GTGD TB ≥10 tỷ và giá ≥5, xem _select_liquid_movers), giao với fundamentals.parquet. File parquet này phủ toàn bộ kho. Mã tài chính cũng nằm trong tập này: tài chính chỉ bị loại khỏi phần xếp hạng canon, KHÔNG bị loại khỏi bộ lọc xóa dòng. Vì vậy dòng nhắc EIB, SSI hay GMD đều bị xóa. Tôi đã chạy thử cả enforce_risk_section lẫn toàn chuỗi apply_brief_guards và tái hiện đúng kết quả đó.  BỎ SÓT (nặng hơn): bộ lọc khớp ký hiệu mã với chữ thường gặp, nên xóa nhầm cả dòng vĩ mô thuần. Docstring của hàm lại hứa giữ những dòng này. Đã c  
  _Nguồn:_ vnstock_brief_guards_sections.py:1084-1092 (`_fund_kw`, `_is_fundamental`, lọc `macro`). Phạm vi tập mã: vnstock_brief.py:2509-2512 cùng `_select_liquid_movers` (vnstock_brief.py:2061-2066, 2096). Prompt đồng phạm: vnstock_brief.py:345 (close, mục (a)) và 257 (sáng). Thứ tự chạy: apply_brief_guards 
- **[data/F3] medium** · 🏆 Dẫn dắt & Tụt hậu / 💰 Dòng tiền (đóng góp pp ngành) — Phát hiện ĐÚNG về cơ chế và về mâu thuẫn ngay trong brief. Tuy vậy có 3 chỗ cần sửa lại cho chính xác, và gợi ý sửa như đang viết sẽ làm hỏng nhóm tuỳ biến.  (1) Cơ chế: 'đóng góp pp' cấp NGÀNH = (vốn hoá ngành / tổng vốn hoá) × 'Giá 1T %' ngành. 'Giá 1T %' ở đây là trung bình cộng ĐỀU chg5 của các mã. Còn 'đóng góp pp' cấp MÃ = (vốn hoá mã / tổng) × chg5 mã. Hai mẫu số giống nhau, cùng một universe, không đếm trùng: runner gom ngành theo phân hoạch `_sector_group`. Vì vậy tổng đóng góp của các mã trong ngành KHÔNG bằng đóng góp của ngành. Chỉ số ngành vì thế không phải 'đóng góp vào chỉ số' theo nghĩa của nhãn.  (2) Số trong brief 05/10 tự mâu thuẫn: - MSR có +0.103pp / 14.3% ⇒ trọng số 0.72%, tức khoảng 63–69% vốn hoá Khai khoáng (1.1%). - −0.014/1.1% ⇒ TB cộng đều của ngành ≈ −1.3%. - Tính theo vốn hoá, đóng góp ngành = 0.103 + 0.0038 × r_rest, với r_rest là mức đổi tuần (tính theo vố  
  _Nguồn:_ Phần định lượng hoàn toàn deterministic (LLM chỉ chép lại số): - vnstock_runner.py:716: TB cộng đều chg5 ở `agg()`. Gom nhóm tại :772-776. - vnstock_brief.py:2463-2469: `_weight`/`_1d_contrib` cấp mã. :2470-2474: top_stocks_per_sector theo ngành gốc. :2477-2486: `_1d_contrib` cấp ngành. - vnstock_br
- **[data/F4] high** · 📋 Khuyến nghị đang mở × 📅 Sự kiện sắp tới (GMD) — Phát hiện ĐÚNG ở phần lõi, chỉ cần sửa vài chi tiết. (1) Khối 📋 "Khuyến nghị đang mở" do Telegram ghép (`_open_recs_block`, được gọi ở push_close_brief, vnstock_telegram.py:686), nằm NGOÀI apply_brief_guards. Hàm này không tra sự kiện quyền nào, nên dòng GMD BUY @78 (ngày 11/20) không có ⚠️ GDKHQ, dù mục 📅 báo GMD thưởng 50%, GDKHQ 07/10. Vùng "rec" của enforce_exdate_levels không chết hẳn: nó vẫn chạy cho mục 💡 Đề xuất giao dịch trong thân brief. Nó chỉ không bao giờ với tới khối 📋 phía Telegram. (2) Sổ lệnh sẽ ghi một lệnh thủng SL giả. Lý do là entry/TP/SL lưu trong SQLite theo cơ sở CŨ, còn kho giá là chuỗi đã điều chỉnh (notes 13/08 (l): 28/28 sự kiện khớp "đã điều chỉnh"), và reconcile không có bước quy đổi nào qua GDKHQ. Cơ chế thực tế khác mô tả một chút. Sau 07/10, nguồn rebase toàn chuỗi khoảng 1/1.5. Cửa gác V1 (vnstock_updater.py:557-570) cách ly GMD ở trạng thái basis_drift,  
  _Nguồn:_ Hiển thị: vnstock_telegram.py:359-421 (_open_recs_block, dòng in lệnh :402-406, ghép vào close brief :686). Chấm lệnh: vnstock_train.py:541-566 (_grade_rec) + :569-650 (reconcile_recommendations; :627 cắt post, :636 chấm, :647 đóng). Guard không với tới: vnstock_brief_guards_sections.py:1248-1310 (v
- **[data/F5] medium** · 📋 Watchlist sáng mai × 📋 Khuyến nghị đang mở (DCM) — Phát hiện đúng ở phần chính, nhưng ba chi tiết cần sửa.  Phần đúng: cùng một tin nhắn nói ngược nhau trên cùng mã DCM. Watchlist ghi "DCM GIẢM TỶ TRỌNG/TRÁNH nếu thủng 32,300" (do LLM viết), khối 📋 lại ghi "DCM BUY @33 (ngày 3/20)" là lệnh mua đang mở (template phía Telegram). Không có guard nào đối chiếu hai khối này.  Ba chỗ cần sửa: (1) "Không biết SL ở đâu" là sai một phần. Bản brief đưa cho người đánh giá đã bị nén. Telegram thật in từng dòng lệnh ở dạng "DCM BUY @33 → TP +x% | SL y% | ngày 3/20", nghĩa là SL CÓ hiện. Có điều nó là % tính từ giá vào đã làm tròn chứ không phải mức giá tuyệt đối, nên người đọc phải tự tính mới so được với 32,300. (2) "Giá 32,500 đã thấp hơn giá vào lệnh" không khẳng định được. "@33" được làm tròn bằng `.0f` (với giá ≥10), nên giá vào thật nằm trong khoảng [32.5, 33.5). Chỉ nói được là giá hiện ≤ giá vào. (3) Gốc rễ nằm sâu hơn chỗ "thiếu guard chéo mụ  
  _Nguồn:_ Hai nguồn độc lập ghép vào cùng một tin: 1. Watchlist do LLM viết theo prompt ở `vnstock_brief.py:328-334`. Prompt không nhắc đối chiếu lệnh đang mở, và block Khuyến nghị ở `vnstock_brief.py:4352` chỉ đưa `fresh[:5]`, nên DCM (lệnh ngày 3) không lọt vào prompt. 2. Khối 📋 lệnh đang mở do template `vn
- **[data/F6] low** · 📌 Danh mục đang giữ (EIB) — Phát hiện đúng về cơ chế, nhưng mức độ nên hạ xuống low. enforce_nn_frame_labels chỉ soi 12 ký tự sau "tỷ" để biết đã có nhãn khung chưa: after = out[m.end():m.end()+12]. Chuỗi " trong 1 tuần" dài 13 ký tự nên cửa sổ chỉ thấy " trong 1 tuầ", không có chữ "tuần". Phần cửa sổ trước số (từ đầu dòng tới số) cũng không có "tuần"/"1t", nên guard gắn thêm " (1 tuần)" và ra "-2,783 tỷ (1 tuần) trong 1 tuần". Hai nhánh đều dính cùng lỗi: nhánh tên-trước-số (dòng 868) và nhánh số-trước-tên _fix_rev (dòng 887). Cửa sổ cố định này còn làm hỏng các cách viết khung khác: " (1T)" ra "(1 tuần) (1T)", " trong 5 phiên" ra "(1 tuần) trong 5 phiên", " trong vòng 1 tuần" và " trong 1 tuần qua" cũng bị gắn trùng. Lý do: phần soi phía sau chỉ tìm chữ "tuần" chứ không tìm "1t"/"phiên", và cửa sổ quá ngắn. Số liệu không sai: -2,783 đúng là NN 1 tuần của Ngân hàng, và cả hai nhãn đều nói 1 tuần. Đây chỉ là nhãn l  
  _Nguồn:_ vnstock_brief_guards_sections.py:868 (nhánh tên-trước-số, _fix) và :887 (nhánh số-trước-tên, _fix_rev), trong hàm enforce_nn_frame_labels (dòng 828). Hàm được nối ở vnstock_brief_guards.py:259 trong apply_brief_guards.
- **[data/F7] low** · Header ⚖️ Regime × 📊 Tổng kết phiên — Phát hiện có thật ở brief hôm nay, nhưng cần sửa lại cho đúng trên ba điểm.  (1) Mâu thuẫn không chỉ nằm giữa header và thân bài, mà có ngay trong phần chữ của AI. Prompt cấp cho model hai thứ cùng mang tên "regime": - Khối bias floor in "regime score -5", lấy từ `vnstock_regime.load_regime`. TLDR chép lại thành "regime score -5". - Khối "## Quant Market Regime" in "📉 Slight bearish bias | conviction=-0.03", lấy từ `market_analyzer.market_regime`. Phần Tổng kết chép lại thành "Regime nghiêng giảm nhẹ (conviction -0.03…)".  Số nào cũng đúng theo định nghĩa của nó: - Header: conviction = |score|/n = 5/7 = 71%. - Thân bài: conviction = composite ngành trung bình, còn nhãn ra "Slight bearish" vì (3−8)/31 = −0.16, nằm trong khoảng (−0.3, −0.1).  Brief không ghi chỗ nào rằng đây là hai thước đo khác nhau. Người đọc vì vậy thấy "Bear 71%" đứng cạnh "giảm nhẹ −0.03". Riêng trường "conviction" ma  
  _Nguồn:_ - Header: vnstock_telegram.py:255-277 (`_regime_block`, dòng in ở :273), gọi ở :634 và :680. conviction tính ở vnstock_regime.py:204. - Prompt: vnstock_brief.py:3133-3137 (khối Quant Market Regime, trường `conviction=`) và vnstock_brief.py:3088-3093 (bias floor in "regime score"). - Nguồn nhãn và tr
- **[data/F8] low** · 💰 Dòng tiền (Luân chuyển — Dầu khí) — Phát hiện đúng ở phần cốt lõi, nhưng cần sửa ba chỗ.  (1) Khối prompt "## Distribution warning (giá xanh, tiền đang thoát)" chỉ nhận ngành có cờ Divergence (giá 1 tháng tăng nhưng Net BS 1 tháng < -5% KL) VÀ composite > 0. Vì vậy _composite_tag chỉ có thể in ra "trung tính" (0 < c < 0.2), "tích luỹ" (≥ 0.2) hoặc "tích luỹ mạnh" (≥ 0.6), và KHÔNG BAO GIỜ in "phân phối". Ngay dưới khối, prompt còn dặn "DÙNG nhãn chữ (phân phối/tích luỹ…)". Thế là code đưa cho model đúng cặp nhãn tự đá nhau. Chữ "dù nhãn tín hiệu ngành là tích luỹ" của brief bắt nguồn từ đây, không phải do model bịa. Tuy vậy, "model buộc phải viết câu rào" là nói quá: model không bị ép, nó chỉ được mớm mâu thuẫn. Nói "không phải do thị trường" cũng chỉ đúng một nửa: phân kỳ là thật (composite dương nhờ momentum/volume trong khi flow âm). Sai là ở chỗ gọi một điểm pha trộn (0.35 momentum + 0.30 volume + 0.35 flow) bằng chữ c  
  _Nguồn:_ Chỗ gốc là các khối prompt deterministic: - vnstock_brief.py:3386-3395 (_composite_tag) - vnstock_brief.py:3495-3500 (khối Distribution warning + câu dặn dùng nhãn phân phối/tích luỹ) - vnstock_market_analyzer.py:755-757 (distribution chỉ lấy composite > 0)  Chỗ lọt là guard #23 enforce_composite_ro
- **[data/F9] low** · 🏆 Dẫn dắt & Tụt hậu — Phát hiện chỉ đúng một phần. Ý chính "stale" là sai. Dùng khung 1 TUẦN cho mục Dẫn dắt/Tụt hậu trong brief chiều là thiết kế có chủ đích và có ghi lại: docs/CLAUDE-NOTES.md:66-69 ghi "Giá 1T % = đổi 1 TUẦN… KHÔNG ghi 'hôm nay' cho số này (không có data đổi-1-phiên cho từng mã)", dòng 77 và 422 cũng nói vậy. market_overview chỉ có chg5/chg20/chg60 (vnstock_runner.py:431-455), không có cột % đổi 1 phiên, và ctx của brief không có dữ liệu "ai kéo chỉ số hôm nay". Dòng Tụt hậu đã ghi "(1 tuần)". Họ VIN đóng góp -0.443pp trong tuần và tin "Vingroup giúp cắt chuỗi giảm" trong phiên không mâu thuẫn nhau. Việc brief không nêu mã kéo chỉ số hôm nay là thiếu tính năng, không phải số sai.  Phần có thật, mức thấp: (1) Dòng phủ định "Dẫn dắt: Chưa có nhóm dẫn dắt rõ ràng (… +0.049pp …)" thiếu nhãn "(1 tuần)". Điều này vi phạm luật đã ghi ở CLAUDE-NOTES:68: "mỗi dòng + đóng góp pp đều phải ghi (1 tuần  
  _Nguồn:_ Prompt vnstock_brief.py:3065 (nhánh phủ định thiếu "1 tuần", có "< 0.05" để model chép) và 3069. Guard vnstock_brief_guards_sections.py:559-564 (câu canon phủ định thiếu "1 tuần") và :576 (chấp nhận mọi dòng có từ phủ định nên không chuẩn hoá). Tên khoá sai: vnstock_brief.py:2469, 2484 (_1d_contrib)
- **[data/F10] low** · 💡 Đề xuất giao dịch × 📋 Khuyến nghị đang mở — Lỗi có thật, nhưng nguyên nhân gốc không nằm ở "LLM chép". Đây là hai hàm định dạng giá anh em đã lệch nhau. Mục 💡 Đề xuất và khối 📋 đọc CÙNG một dòng trong sổ: vnstock_memory.open_recommendations() trả bản mới nhất của mỗi mã, nên entry_price của DRI là một con số duy nhất, khoảng 16.6. Prompt in giá qua vnstock_brief._fmt_rec_price (vnstock_brief.py:4123-4147). Hàm này đã được nới vào ngày 19/08 (CLAUDE-NOTES khoảng dòng 11715, vết "SBT entry=24") để giữ 1 chữ số thập phân cho giá trong dải 10–100. Còn vnstock_telegram._fmt_price (vnstock_telegram.py:341-356, gọi ở dòng 403 trong _open_recs_block) KHÔNG được vá theo: giá ≥10 vẫn in kiểu f'{p:,.0f}'. Vì vậy cùng một lệnh mà hai khối in hai mốc giá: DRI 16.6 thành @17 (lệch 2.4%), BFC 57.2 thành @57 (lệch 0.35%), DGW 47 trùng nhau. Tác hại cụ thể: dòng 📋 thật in "@17 → TP +14.5% | SL -6.6%", trong đó % tính từ entry chính xác 16.6. Người  
  _Nguồn:_ vnstock_telegram.py:341-356 (_fmt_price, nhánh `f"{p:,.0f}"` cho giá ≥10), được gọi tại vnstock_telegram.py:403 trong _open_recs_block (359-416). Đối chiếu với vnstock_brief.py:4123-4147 (_fmt_rec_price, bản đã vá 19/08), dùng trong _recommendation_block ở vnstock_brief.py:4352-4357. Phần "liệt kê h
- **[data/F11] low** · Toàn brief (đơn vị giá) — Phát hiện đúng. Một tin nhắn đang in giá cổ phiếu theo hai đơn vị mà không chỗ nào ghi nhãn đơn vị. (a) Watchlist in đồng đầy đủ: 'SSB Giá 17,450', 'thủng hỗ trợ 17,100', 'DCM Giá 32,500'. Đây là chủ ý: prompt nhân 'last' (nghìn đồng) ×1000 làm mốc neo, và các test trong tests/test_brief.py:335-466 ghim dạng 'Giá 70,700'. (b) Ba khối còn lại in nghìn đồng: Danh mục ('vốn 20.50 | hiện 16.40'), Đề xuất giao dịch ('entry 16.6 · TP 19') và Khuyến nghị đang mở ('@17', '@9.21'). Ví dụ dễ thấy nhất không phải EIB đặt cạnh SSB mà là cùng một mã in hai đơn vị trong một tin: DCM ở Watchlist là 'Giá 32,500', ở lệnh mở là 'DCM BUY @33'. Có thêm một lệch phụ trong chính đơn vị nghìn đồng. DRI ở Đề xuất ghi 'entry 16.6', còn ở lệnh mở ghi 'DRI BUY @17'. Lý do là _fmt_price của telegram bỏ số lẻ khi giá ≥10, trong khi _fmt_rec_price của brief đã được nới (19/08) để giữ 1 số lẻ cho giá dưới 100. Số liệu  
  _Nguồn:_ Phần lớn origin mà phát hiện nêu là đúng: vnstock_brief.py:3516, vnstock_brief_canon.py:320-322 (hàm nằm ở 317-325), vnstock_telegram.py:341-356 (_fmt_price), với dòng gọi nằm ở vnstock_telegram.py:403. Phát hiện còn thiếu nguồn của mục Đề xuất giao dịch: vnstock_brief.py:4123-4147 (_fmt_rec_price) 
- **[data/F12] low** · 💡 Đề xuất giao dịch — Phát hiện ĐÚNG ở phần chính, nhưng một lập luận sai. Ba dòng DRI/BFC/DGW trong mục 💡 ("- DRI: entry 16.6 · TP 19 · SL 15.5 (~4,400 cp). …") dùng nhãn tiếng Anh entry/TP/SL và KHÔNG có động từ chiều lệnh (không BUY, không MUA). Guard enforce_rec_line_format để lọt cả ba dòng vì _REC_RAW_LINE_RE bắt buộc có token BUY|MUA và dấu '='. Dòng data gốc là "- DRI BUY entry=16.6 TP=19 SL=15.5 · KL gợi ý ~4,400 cp (rủi ro 1% NAV)" (vnstock_brief.py:4357-4372). Model đã viết lại một nửa: bỏ BUY và '=', giữ nhãn Anh, nên rơi đúng vào khe hở của regex.  SAI ở chỗ nói "template quy định 'MUA vùng · chốt lời · cắt lỗ'". Prompt pipeline của mục 💡 (_AFTERNOON_TEMPLATE, vnstock_brief.py:363) chỉ ghi "[Liệt kê tối đa 3 mã với entry/TP/SL từ block "Khuyến nghị"]". Mẫu "MUA vùng · chốt lời · cắt lỗ" có ở hai nơi khác: mục Watchlist (vnstock_brief.py:333) và skill tay /brief-close (.claude/skills/brief-close/S  
  _Nguồn:_ LLM, có prompt góp phần: vnstock_brief.py:363 (_AFTERNOON_TEMPLATE, mục 💡 gọi tên "entry/TP/SL" và không đưa mẫu VN). Guard trượt: vnstock_brief_guards_sections.py:1690-1696 (_REC_RAW_LINE_RE bắt buộc BUY|MUA và '='), enforce_rec_line_format ở 1726-1746, được nối tại vnstock_brief_guards.py:269. Nhậ
- **[data/F13] low** · 📚 Báo cáo vĩ mô & phân bổ — Phát hiện có thật, nhưng chỉ là vấn đề trình bày, không sai số. Mọi con số trong mục 📚 đều đúng theo định nghĩa: báo cáo 10/07 có tuổi 87 ngày so với as_of = phiên 05/10, nên w = (90−87)/60 = 0,05. Consensus là trung bình có trọng số, ra −1,00 vì cả hai báo cáo đều là −1. strength = min(1; 1,05) = 1 nên tilt đủ +1 band. Bỏ báo cáo 10/07 đi thì kết quả vẫn y hệt (−1,00, tilt +1, band B4). Vậy tilt và band KHÔNG bị thổi phồng.  Chỗ lệch thật nằm ở cách in: (1) `n_reports` đếm mọi báo cáo có w > 0, kể cả w = 0,05, nên dòng "Consensus 2 báo cáo" gợi ý có hai góc nhìn độc lập. Thực tế tổng trọng số chỉ ~1,05, gần 95% đến từ báo cáo 04/10, và cả hai cùng nguồn HedgeAcademy. (2) Tóm tắt báo cáo tháng 7 ("thị trường 'CHỜ'") được in ngang hàng báo cáo hôm qua, không có trọng số.  Reviewer nói hơi quá ở ý "không kèm tuổi": ngày [2026-07-10] có in, người đọc tự suy được tuổi. Thứ thiếu là trọng số   
  _Nguồn:_ Origin chính: `vnstock_brief_canon.py:254-292` (`_macro_reports_body_lines`); dòng báo cáo ở :276-284, dòng consensus ở :285-290. Hàm này được guard `vnstock_brief_guards_sections.py:200-230` (`enforce_macro_reports`) ghim lại, gọi từ `vnstock_brief_guards.py:249`. Số `n_reports` sinh ở `vnstock_rep
- **[data/F14] low** · 🌐 Vĩ mô (Đi ngang/chưa có kỳ mới) — Con số trong brief đúng, và vế "seed hay portal" trong phát hiện không trúng. Phần thật nằm ở chỗ khác: không có dấu vết nào cho biết portal SBV được kiểm thành công lần cuối khi nào. Lỗ hổng chỉ tiềm ẩn, hôm nay không sai số nào.  (1) "4.50% (2023-06-19)" không phải số cũ ba năm. 2023-06-19 là ngày hiệu lực của QĐ 1123 hiện hành, đúng thiết kế. Từ 17/07/2026 registry tự động lấy từ portal SBV (structure 3450482, source="sbv_portal"), đã verify trên máy user ngày 17/07 (CLAUDE-NOTES:2265-2282).  (2) Phân biệt seed và portal gần như vô nghĩa. Seed chỉ được ghi khi history rỗng (vnstock_macro.py:242-245), mà history đã có entry 2023-06-19 mang nhãn sbv_portal. Vì vậy brief hôm nay gần như chắc chắn không lấy từ seed.  (3) Lỗ hổng thật có ba chỗ. Thứ nhất, _fetch_sbv_policy nuốt mọi lỗi và trả None (vnstock_macro.py:811-817). Thứ hai, refresh_policy không lưu thời điểm fetch thành công nào   
  _Nguồn:_ - Chỗ in ra: vnstock_brief_canon.py:128-134 (`_macro_body_lines`, nhánh `flat`). - Chỗ ghi giá trị: vnstock_macro.py:646-655, cùng `_fetch_sbv_policy` ở 811-817 và vnstock_sbv_rates.py:216-226 (`refresh_policy`, không có checked_at). - Chỗ mù giám sát: vnstock_doctor.py:44-62 (`_MACRO_MAX_AGE_DAYS` 
