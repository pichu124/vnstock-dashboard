# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 25/08/2026, sau phát 18:00.

## 🏷️ NHÃN MÁY — quy tắc gốc: KHO đồng bộ, CODE thì không

`C:\vnstock\data_warehouse` là **Junction** trỏ sang
`E:\Dropbox\vnstock_data\data_warehouse`. Repo `C:\vnstock` đi bằng **git**.

| Nhãn | Nghĩa |
|---|---|
| ○ **MỘT LẦN** | Đụng `data_warehouse`. Dropbox lo máy kia — **đừng làm hai lần**. |
| ⇄ **CẢ HAI** | KHÔNG nằm trong kho: `git merge`, pip, venv, task lịch, biến môi trường, `run_daily.log`. |
| 🖥️ **DESKTOP** | Máy chạy pipeline (`PICHU`, 2 task lịch): log phát đêm, `Get-ScheduledTaskInfo`, brief tự động. |
| 💻 **LAPTOP** | Thử nghiệm rủi ro (`CFA-BINHLD-LT`, không task) — hỏng cũng không mất brief đêm. |

**Máy đang ngồi là TRẠNG THÁI DÍNH** (chốt 20/08): user báo đổi máy thì mới
đổi; không báo thì giữ nguyên máy của lượt trước. Đừng suy từ đường dẫn venv —
cả hai đều `C:\vnstock`, venv đổi theo TÀI KHOẢN đăng nhập. Thật sự chưa biết
thì: `$env:COMPUTERNAME; Get-ScheduledTask -TaskName 'VnStock *'` (2 task =
desktop). **Phiên hiện tại: 🖥️ DESKTOP.**

---

# 🔴 CÒN PHẢI LÀM

## 0. 🔬 Đối chứng `fix-units` — 🖥️ desktop, CHỈ ĐỌC, làm TRƯỚC

Bản vá 26/08 lọc bằng thống kê footer parquet trên đường **GHI KHO GIÁ**. Tôi
chứng minh nó tương đương và có 16 test canh — nhưng bạn phải tự kiểm được,
không phải tin lời tôi. Hai lượt CHỈ ĐỌC (`--dry-run` không sửa file nào):

```powershell
python run.py fix-units --dry-run --json
$env:VNSTOCK_FIXUNITS_FOOTER_PRUNE = "0"
python run.py fix-units --dry-run --json
Remove-Item Env:VNSTOCK_FIXUNITS_FOOTER_PRUNE
```

* **`fix_count` hai lượt BẰNG NHAU** ⇒ phép lọc đúng là tương đương. Đó là
  điều duy nhất phải khớp.
* `skipped_by_footer` (lượt 1) cho biết bỏ qua được bao nhiêu mã — đó là phần
  thời gian tiết kiệm.
* Chênh thời gian giữa hai lượt là mức lợi thật trên đĩa Dropbox của bạn.

⚠️ Nhớ `Remove-Item Env:...` (hoặc mở PowerShell mới) trước 18:00.

---

## 1. 📏 Đo SẠCH thời gian phát — 🖥️ desktop, 1 lệnh

Phát 25/08 chạy **69,0′** (từ 166,3′), đệm dưới trần task lên **111′**. Nhưng
số đó **không sạch**: cùng ngày đã chạy tay `run.py sync`, và `updater 308s`
nhanh hơn cả lượt TẮT cửa gác (2.224s) — bản vá không thể giải thích nổi mức
đó. Cần một phát trong ngày **không chạy tay gì trước**:

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern '⏱ TỔNG|⏱ CHẶNG' | Select-Object -Last 4
```

⚠️ **Chưa đo được** — lượt grep 25/08 trả về đúng 4 dòng CŨ. `run_daily.log`
xoay vòng và giữ nhiều đêm trong một file, mà dòng `⏱` thì trần trụi không
mang ngày ⇒ không phân biệt được đêm nào.

**Đã vá:** từ HEAD, cả hai dòng mang dấu thời gian —
`⏱ TỔNG [2026-08-26 18:05] 69.0 phút …`. Nên lần sau nhìn là biết ngay dòng
nào mới.

**Điều kiện đo SẠCH:** một ngày **KHÔNG chạy tay** `run.py sync` / `run.py all`
trước phát 18:00. Thấy dòng có dấu ngày MỚI thì dán cho Claude **một lần** rồi
đóng mục này. Chi tiết: U29.

## 2. 💳 Quyết Cerebras 402 — ○ máy nào cũng được

Model watch T7 22/08: **Cerebras HTTP 402 "Payment required"** ở cả hai model.
Đây là hỏng **TÀI KHOẢN**, không phải model chết — đổi slug KHÔNG cứu được.

Hệ thống vẫn chạy, nhưng lưới dự phòng mỏng hẳn:

| Điểm | Còn sống |
|---|---|
| [1] sentiment | Gemini → Groq (từ 4 nấc còn 2) |
| [3-6] digest | Gemini + nemotron · Groq×2 → Gemini-lite |
| [7] brief | Gemini (agent CHÍNH) |

⚠️ **Gemini nay gánh cả ba chỗ** — nghẽn Gemini là hụt nhiều nơi cùng lúc.

Ba lựa chọn: **kệ** (rẻ nhất, rủi ro dồn vào Gemini) · **nạp tiền Cerebras**
(về nguyên trạng, không đụng code) · **tìm free thay thế** — phải probe SỐNG
trước rồi báo Claude:
```powershell
python scripts\probe_models.py --slug "OpenRouter=<slug>"
```

## 3. ⏰ NSO qua mạng khác — 🖥️ desktop, CÓ HẠN

CPI / IIP / GDP / cán cân thương mại đang dùng cache `as_of 2026-07-31`. Kỳ
tháng 8 công bố **cuối tháng** — không kéo được là brief nói số vĩ mô cũ, mà
**doctor KHÔNG báo giúp** (nó chỉ biết "fetch hỏng", không biết "số đã lỗi thời").

Phát 4G từ điện thoại, nối máy vào, rồi:
```powershell
python run.py doctor --net
```
NSO ✅ = mạng NHÀ chặn ⇒ xử ở router/ISP, **không đụng code**.
Vẫn ❌ = nguồn thật sự đổi ⇒ lúc đó mới đáng sửa `vnstock_nso`.

*(Jina ⚠️ cùng cụm nhưng **không gấp** — chỉ làm tin chấm bằng title+summary.)*

## 4. 💻 Laptop — merge + nâng vnstock 4.0.7 TRƯỚC desktop

Laptop đang ở `2.447`, HEAD là **`2.550`**.

```powershell
cd C:\vnstock
git pull origin claude/tong-hop-cong-viec-test-w8mvrc
python run.py test          # phải ra 2.597 passed
```

**📦 vnstock 4.0.7 đã ra — cổng gỡ chặn 4.0.6 đã mở.** Đúng thứ tự:
1. 💻 Laptop TRƯỚC: `pip install vnstock==4.0.7` → `run.py doctor --net` +
   `run.py test` **ngay**.
2. Chạy vài ngày xem có gì lạ.
3. Sạch rồi mới đụng 🖥️ desktop, và **không nâng sát 18:00**.
4. Hỏng thì lùi: `pip install vnstock==4.0.4 vnai==2.4.8`.

Desktop giữ 4.0.4 — nó chạy phát tối, không phải chỗ để thử.
*(4.0.6 làm chết mọi lệnh gọi mạng — `env.py:136 UnboundLocalError`.)*

---

# 🔔 MÁY TỰ NHẮC — không phải việc gõ tay

Chạy `python run.py doctor` và chỉ **nhìn badge**. Vàng ở đây thường là dấu
hiệu guard đang LÀM VIỆC, không phải hỏng.

| Badge | Khi nào gọi Claude |
|---|---|
| **Sổ theo dõi nghi ngờ brief** | Chuyển `⚠️ ĐỦ mẫu, đáng quyết` (Op.CF/vốn hoá · câu dòng tiền ngoại ngược data) |
| **Hiệu suất auto-heal** | `⚠️` = 0 lành dù đủ mẫu ⇒ quyết hạ trần `VNSTOCK_AUTOHEAL_BUDGET_S=120` hay tắt hẳn |
| **Lệch cơ sở — mã bị cách ly** | Có mã ⇒ `python scripts\rebase_ticker_history.py --ticker <MÃ> --apply` |
| **Nới OHLC (bar tự mâu thuẫn)** | Nới sát trần 20% ⇒ soi lại bar đó |
| **Rổ VN30** | `⚠️ rổ thật đã đổi` ⇒ dán dòng badge cho Claude |

---

# 🟠 VIỆC CỦA CLAUDE — nói "làm đi" là chạy

| # | Việc | Trạng thái |
|---|---|---|
| ~~1~~ | **Pivot THẬT cho mốc watchlist** | ✅ **XONG 26/08** — `ticker_sr_levels` (pivot 60 phiên, bỏ 2 bar cuối, có 3 sàn nhiễu). Thiếu vế nào thì NÓI là thiếu, không bịa. *(Recon lật kế hoạch: `_ticker_pivots` là hàm SAI — trả chuỗi, làm tròn 1,2%, không sàn nào.)* |
| ~~2~~ | **`screener` 1.318s** | ✅ **XONG 26/08** — nó quét kho **14 lần y hệt nhau** (14 preset, filter chỉ áp SAU khi đã đọc + tính). Nhớ chỉ báo ⇒ 14 lượt → 1. |
| ~~3~~ | **`fix-units` 316s** | ✅ **XONG 26/08** — lọc bằng **thống kê footer parquet** (tương đương chứng minh được, không thêm state), + chỉ giải nén `time`/`close`. |
| 4 | **Bỏ hay giữ đường CafeF `cash-dividends`** (404 từ 19/08) | Vietstock đã trả cả sự kiện tiền mặt ⇒ code chết trông như code sống |
| 5 | **Vòng lặp Net BS trong screener** — gọi `order_stats()` TUẦN TỰ cho MỌI mã (~1.000 lần), `sleep(0.15)` ⇒ sàn 135-165s; cache TTL 12h < nhịp 24h nên **nguội mỗi đêm** | Ứng viên co-equal với #2, chưa tách được khỏi 1.318s nếu chỉ đọc code |

**📏 Phát kế tiếp là phép đo của cả ba bản vá** — dán `⏱ TỔNG` + `⏱ CHẶNG` +
dòng `screener` như thường lệ.

---

# ⏳ TỰ ĐẾN — chỉ đọc

* **T7 hàng tuần**: model watch. Bản mới gộp lỗi TÀI KHOẢN thành một dòng 🏦
  thay vì n dòng ❌ (U24).
* **Vài đêm tới**: #32 mới 39 lệnh, chỉ hơn sàn 30 đúng 9 — một vòng tune xấu
  là mục Khuyến nghị tự tắt. Close 24/08 báo **14 lệnh ẩn** (tăng từ 11) ⇒
  chiến lược nguồn vẫn CHƯA đạt kiểm định. Đó là cổng đang đóng, không phải lỗi.
* **~2 đêm nữa**: hàng đợi auto-heal sạch (1.704 → 1.631 → 778 → …). Rút bằng
  LƯU TRỮ chứ không phải bằng chữa — `healed = 0 / 4.707 lượt` qua ba đêm.

---

# ✅ ĐÃ ĐÓNG — không phải làm lại

| Việc | Kết quả |
|---|---|
| Lệch cơ sở kho giá | **76 mã** đã chữa · quét ra `160 mã KHÔNG đổi bậc` · V1 chặn tái phát ở đường ghi |
| Rổ VN30 kỳ 08/2026 | Lấy động (API → cache → hằng số) · VÀO BSR·LPB·MCH·TCX·VPL, RỜI BCM·BVH·PLX·POW·TPB · cả 30 mã có giá trong kho |
| Live mode | `verify_wss_live` ✅ cả 3 bất biến (24/30 mã volume) + **mắt người** xác nhận heatmap chạy |
| Tốc độ heatmap | Fragment 5s → 2s · tầng nóng (VN30 mỗi vòng, ~1.100 mã mỗi 5 vòng) |
| Rủi ro chạm trần task | 166,3′ → 69,0′ ⇒ đệm 13,7′ → **111′** *(số chưa sạch — xem việc #1)* |
| Phát tự động trọn vẹn | 21/08, 24/08, 25/08 đều đủ 14 bước và **có brief Telegram** |
| Chất lượng brief | Guard số chỉ số (trạng từ) · dọn khối tin · GDKHQ không cảnh báo cho ĐHĐCĐ · dải ±3% gọi đúng tên |
| Đồng bộ code | 🖥️ desktop `2.553 passed / 97,37s` = HEAD (25/08) |
| Sổ lệnh | **Không mất** — 805 briefs · 148 rec · 138 outcome |
| Rác `C:\proc` | **Không tồn tại** — Claude suy nhầm là đã tạo, user kiểm 25/08 ra PathNotFound (U26) |
