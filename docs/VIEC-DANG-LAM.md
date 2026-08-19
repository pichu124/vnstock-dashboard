# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Đây là bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) nằm ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 19/08/2026.

## 🏷️ NHÃN MÁY — mọi việc trong file này BẮT BUỘC có một nhãn

| Nhãn | Nghĩa |
|---|---|
| 🖥️ **DESKTOP** | Chỉ chạy được trên máy chạy pipeline (có 2 task lịch). Laptop không có log / task / kho được cập nhật đêm. |
| 💻 **LAPTOP** | Chỉ nên làm trên laptop (thường là thử nghiệm rủi ro — hỏng cũng không mất brief đêm). |
| ⇄ **CẢ HAI** | Phải làm **lặp lại trên từng máy**. Hai kho KHÔNG tự đồng bộ (đã bỏ Dropbox) — làm một máy là máy kia vẫn hỏng. |
| ○ **MÁY NÀO CŨNG ĐƯỢC** | Kết quả như nhau ở đâu cũng vậy (chạy test, đọc code). |

**Xác định đang ngồi máy nào** (2 giây, làm trước mọi thứ — đừng đoán bằng
đường dẫn `C:\vnstock` hay tên venv, hai máy cài giống hệt nhau, đã nhầm 19/08):

```powershell
$env:COMPUTERNAME; Get-ScheduledTask -TaskName 'VnStock *' | Select-Object TaskName
```
Ra 2 task = **desktop**. Rỗng = **laptop** (`CFA-BINHLD-LT`).

---

## 🔴 VIỆC CỦA BẠN

### ⇄ CẢ HAI MÁY · 🔥 SỐ 1 — Chữa 70 mã lệch cơ sở

Việc lớn nhất đang mở. Quét 19/08 trên laptop: **70/159 mã thanh khoản lệch cơ
sở kho/nguồn**, gần trọn VN30, vách rải từ 03–08/2026 (mùa chia cổ tức). Chạy
thử 2 lần đã sạch: **70/70 mã chữa được**, chỉ 3 mã (HCM, KLB, SSB) cần nhân
khối lượng. Kho chưa chữa thì **mọi backtest/kiểm định đều vô hiệu**.

**💻 LAPTOP — làm được NGAY** (vết quét đã có sẵn từ lần chạy 19/08):

```powershell
git fetch origin claude/tong-hop-cong-viec-test-w8mvrc
git merge origin/claude/tong-hop-cong-viec-test-w8mvrc

python scripts\rebase_ticker_history.py --from-sweep --apply
python scripts\probe_price_basis.py --sweep      # kỳ vọng: 0 mã
```

**🖥️ DESKTOP — PHẢI QUÉT LẠI TRƯỚC.** `--from-sweep` đọc
`data_warehouse/_meta/basis_sweep_check.json` — file **local từng máy** (kho nằm
trong `.gitignore`, không đi theo git). Desktop chưa quét lần nào nên chưa có
file này; chạy thẳng `--from-sweep` sẽ báo *"chưa có vết quét"* và không làm gì.

```powershell
python scripts\probe_price_basis.py --sweep           # ~160 lần gọi nguồn, vài phút
python scripts\rebase_ticker_history.py --from-sweep  # chạy THỬ, đọc kỹ
python scripts\rebase_ticker_history.py --from-sweep --apply
python scripts\probe_price_basis.py --sweep           # kỳ vọng: 0 mã
```

Danh sách 70 mã của desktop có thể KHÁC laptop (hai kho lệch nhau) — đó là lý
do bắt buộc quét tại chỗ, không chép danh sách qua.

*Việc này nuốt luôn mục **chữa VVS** cũ: VVS ~13 tỷ/phiên nên nằm trong universe
quét, `--from-sweep` trên desktop sẽ tự bắt. Laptop đã chữa VVS riêng 19/08.*

**An toàn:** mỗi mã tự sao lưu vào `_meta/backup_rebase/<MÃ>_<timestamp>/` trước
khi ghi, ghi nguyên tử, tự kiểm sau khi ghi — tự kiểm fail thì mã đó tự khôi
phục. Cứ để chạy hết rồi đọc tổng kết cuối.

**Sai số đã chấp nhận có ý thức:** PET (thưởng, factor 1.4499 vs bước 0.43) và
F88 (chia tách 2.0000× vs bước 3.08) — bằng chứng khối lượng mâu thuẫn sổ sự
kiện nên công cụ GIỮ khối lượng nguồn. Hệ quả: GTGD lịch sử 2 mã này hụt đúng
bằng factor, chỉ chạm bộ lọc thanh khoản. Ép thủ công: `--ticker PET --volume adjust`.

### ○ Sau khi chữa xong — 3 lệnh chạy lại, máy nào chữa thì máy đó chạy

```powershell
python run.py test                                    # full suite, kỳ vọng 2.228 passed
python run.py validate                                # hợp đồng dữ liệu trên kho vừa chữa
python vnstock_train.py --strategy-only --tier both --mode tune
```

Lệnh thứ 3 là cái đáng giá nhất: nó chấm lại backtest + kiểm định chống-ăn-may
trên chuỗi giá đã liền. **Coi mọi verdict trước 19/08 là VÔ HIỆU** — kể cả #32
(p=0.012, n=94), vì nó được chấm trên 44% universe có bậc giả. Dán kết quả cho
Claude, nhất là số lệnh và p-value mới.

### 🖥️ DESKTOP · ⏰ GẤP — làm TRƯỚC 18:00 bất kỳ ngày làm việc nào

Nếu bỏ qua, task đêm vẫn có nguy cơ bị Windows chấm dứt trước bước brief.

```powershell
cd C:\vnstock
git fetch origin claude/tong-hop-cong-viec-test-w8mvrc
git merge origin/claude/tong-hop-cong-viec-test-w8mvrc
```

Rồi mở PowerShell **quyền Administrator**:

```powershell
$t = Get-ScheduledTask -TaskName 'VnStock Daily Pipeline'
$t.Settings.ExecutionTimeLimit = 'PT180M'
Set-ScheduledTask -TaskName 'VnStock Daily Pipeline' -Settings $t.Settings
(Get-ScheduledTask -TaskName 'VnStock Daily Pipeline').Settings.ExecutionTimeLimit
```
Dòng cuối phải in `PT3H` (hoặc `PT180M`). Xong thì **để yên máy qua 18:00**.

*Vì sao:* phát gần nhất chạy hết **96,6 phút mới tới bước 9/14** (sync 60' +
screener 28'), còn 4 bước nữa mới tới brief → dư địa chỉ 16 phút dưới trần 120.
Một đêm sync phình như 17/08 (74') là vượt trần. Đã sửa sẵn trong
`setup_scheduled_tasks.ps1` (commit 943e5ea) nhưng file đó chỉ có tác dụng khi
đăng ký lại task — lệnh trên là đường tắt.

### 🖥️ DESKTOP · Sáng hôm sau — kiểm 1 phút

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern 'CHANG|CHẶNG' | Select-Object -Last 3
```
Dòng `[sync] ⏱ CHẶNG …` nói sync tiêu 60 phút vào chặng nào (updater / rollup /
fix-units / auto-heal). Dán cho Claude — đây là số còn thiếu để chữa đúng chỗ.

### 🖥️ DESKTOP · Brief chiều — kiểm 1 phút

Telegram có brief chiều không? **Có** = đêm tự động trọn vẹn ĐẦU TIÊN (mở luôn
cổng đang chặn mục "tầng B"). **Không** → chạy lệnh này rồi dán cho Claude:

```powershell
Select-String -Path C:\vnstock\run_daily.log -Pattern '[brief]' -SimpleMatch | Select-Object -Last 5
Get-Content C:\vnstock\run_daily.log -Tail 15
```

### 🖥️ DESKTOP · `doctor --net` — phân xử NSO/Jina

Laptop chạy ra NSO ❌ + Jina ⚠️, cả 3 URL đều `ConnectTimeout`/`ConnectionReset`
— **lỗi tầng kết nối, chưa kết luận được nguồn có hỏng hay không**. Desktop chạy
lệnh này là phân xử được ngay: desktop cũng ❌ = nguồn hỏng thật; desktop ✅ =
chính sách mạng laptop, không phải lỗi code.

```powershell
python run.py doctor --net
```

### ○ Chỉ làm được TRONG GIỜ GIAO DỊCH (9h15–14h30, T2–T6)

Máy nào cũng được — WSS là kết nối mạng thuần, không phụ thuộc kho đêm, và
laptop có kho đầy đủ.

```powershell
python scripts\verify_wss_live.py --duration 120
```
Exit 0 = đạt cả 3 bất biến · 1 = ngoài giờ/thiếu tick (KHÔNG phải fail) · 2 = sai.
Hoặc bằng mắt: mở dashboard → bật 🔴 **Live Mode** ở sidebar → tab **Thị trường**,
xác nhận heatmap VN30 có số nhảy thật.

### 💻 LAPTOP · Thử — sổ sự kiện quyền có dày lên được không (đọc, không ghi)

Sổ sự kiện quyền đang mỏng: trong 70 mã lệch chỉ **3 mã** tra ra được loại sự
kiện. Đây là gốc khiến bộ chữa phải đoán khối lượng bằng heuristic. Lệnh dưới
CHỈ ĐỌC và in ra (không có `--register` = không ghi gì vào kho):

```powershell
python run.py vietstock --ticker PET --fdate 2026-01-01
python run.py cash-dividends --ticker VNM
```
Ra được sự kiện = đường này dùng được, Claude sẽ nối vào bộ chữa. Timeout hết =
mạng laptop chặn (giống NSO/Jina), phải thử lại trên desktop. Dán kết quả.

### ○ ✅ Classifier — ĐÃ XÁC MINH 19/08 (trên laptop), đóng nợ 07/08

`--rerun-flagged VNM` trên laptop in đúng `route: ladder free — Gemini
3.5-flash dẫn đầu`, 1 classified / 0 errors, KHÔNG đòi `ANTHROPIC_API_KEY`.
Bậc thang model free chạy thật, không chỉ chạy trong test.
(Chạy `--classify` thường sẽ báo "All tickers already classified" vì 1652/1652
đã xong — muốn xác minh lại phải dùng `--rerun-flagged`.)

### ⇄ CẢ HAI · ✅ Nâng thư viện — laptop XONG 19/08 · ⏳ desktop chờ soak

vnstock 4.0.6 · vnai 2.5.7 · vnii 0.2.5 trên laptop: 2.196 passed y nguyên, kho
đọc vẫn đúng. **Desktop cố ý CHƯA nâng** — để laptop chạy vài ngày đã, và khi
nâng thì không sát 18:00, nâng xong chạy `doctor --net` + full suite ngay.

⚠️ **Cảnh báo đã trả giá 19/08:** 4.0.6 từng làm chết MỌI lệnh gọi mạng
(`env.py:136 get_hosting_service()` UnboundLocalError) → phải lùi về 4.0.4 mới
probe được. Nếu desktop nâng mà `probe_price_basis` báo `RetryError`/
`UnboundLocalError` thì lùi ngay: `pip install vnstock==4.0.4 vnai==2.4.8`.

---

## ✅ ĐÃ CHỐT — không phải làm lại

* **Vì sao brief không gửi**: phát `all` gần nhất trên DESKTOP **chết ở bước
  `test` (9/14)** với `rc=2 → stopping`, nên train/reflection/doctor/brief chưa
  bao giờ được gọi. Không phải bị bỏ qua, không phải kill-switch, không phải
  marker. Test đó nay đã xanh trên chính desktop (18 passed).
* **Test đó nay ĐÃ XANH trên máy thật** (`18 passed`) — phát chết là chạy trên
  code cũ trước khi merge. Đêm tới sẽ đi qua được bước 9.
* **Máy không thiếu code**: HEAD đã ở đúng commit mới nhất.
* **Log đã bị tự cắt** (còn 1,19 MB) → bằng chứng các phát trước MẤT. Nguyên
  nhân nằm ở việc #1 của Claude bên dưới.

---

## 🟠 VIỆC CỦA CLAUDE — bạn chỉ cần nói "làm đi"

Xếp theo thứ tự nên làm. Mỗi việc xong Claude chạy `run.py test --fast`, bạn chỉ
cần `git fetch origin <nhánh> && git merge origin/<nhánh>` rồi chạy lại test trên máy thật.

> Việc của Claude làm trong container; bạn chỉ cần merge về rồi chạy test —
> ○ **máy nào cũng được**.

| # | Việc | Vì sao đáng | Công |
|---|---|---|---|
| 0 | ⏳ **Mổ `sync` 60 phút** — đã cắm đồng hồ từng chặng (`a83ee51`), **chờ số đêm nay** | Chiếm 62% thời gian chạy. Nghi phạm số 1: `fix-units` quét TOÀN KHO mỗi đêm | chờ đo |
| ~~1~~ | ✅ **XONG 19/08** (`970a504`) — test hết ghi bẩn `run_daily.log` | Đo lại: chạy full suite xong log không đổi **một byte** | — |
| ~~2~~ | ✅ **XONG 19/08** (`a83ee51`) — rec hết bị đóng sớm; lệnh thủng SL nay nhận ra ngay thay vì chờ hết horizon | Verdict #32 từ nay chấm trên đúng khung | — |
| 3 | **Ghi JSON nguyên tử** (12 điểm/7 file) + nối vào lưới `_MUST_BE_ATOMIC` | Pipeline đã bị kill 2 lần; bản cụt còn lây sang file dự phòng | ~30' |
| ~~4~~ | ✅ **XONG 19/08** (`970a504`) — 3 test bộ công cụ đơn vị giá đã vào `--fast` | `--fast` nay 1.636 test | — |
| ~~5~~ | ✅ **XONG 19/08** (`0a3e785`) — doctor có badge "Kill-switch pipeline", đọc cả `.env` | Ẩn số kiểu này từ nay tự lộ | — |
| ~~6~~ | ✅ **XONG 19/08** (`0a3e785`) — `telegram close` qua đúng cửa gác, muốn vượt phải `--force` | Hết bẫy gõ-2-lần và bẫy-câm-brief | — |
| 7 | **Vá gốc lỗ hổng độ tươi** (giờ bị cắt ở `vnstock_brief.py:1095`) | Vá xong thì khỏi phải làm Bước 2 bằng tay nữa | ~1 buổi |

---

## ❓ CHỜ BẠN QUYẾT — nói "khác đi" là Claude đổi, im lặng là Claude làm theo đề xuất

**Q1. Guard chặn tái phát lệch cơ sở (V1)** — đường VCI chính đang ghi đè kho im
lặng, không đối chiếu gì. **Claude bắt tay làm theo phương án dưới**, anh chỉ cần
chặn lại nếu thấy sai:
* **Ngưỡng 1,5%** trên tỉ lệ kho/nguồn của phần bar chồng lấn (bằng ngưỡng
  `--sweep` đang bắt được cỡ cổ tức; 8% của nhánh fallback là quá thô, lọt hết
  70 mã vừa rồi).
* **Có tra sổ sự kiện quyền trước khi báo động** — nhưng sổ mỏng nên tra ra thì
  ghi kèm loại sự kiện vào cảnh báo, tra không ra thì VẪN báo động (không im
  lặng bỏ qua chỉ vì sổ thiếu).
* **Cách ly + cảnh báo**, KHÔNG tự ghi đè: gặp nghi vấn thì bỏ qua lần nối đó,
  đánh dấu mã "cần nạp lại toàn bộ lịch sử", ghi cảnh báo vào `run_daily.log` và
  bật badge trong doctor. Lý do: sync chạy 3h sáng không ai nhìn — tự động ghi
  đè lịch sử lúc đó là đúng loại hành động không nên tự làm.

**Q2. Mốc giờ coi là "phiên đã đóng"** — dùng cho việc #7 ở trên. Đề xuất 15:05
(khớp mốc mà screener đang dùng). Đồng ý thì Claude lấy luôn.

---

## ⏳ TỰ ĐẾN — không phải làm gì, chỉ đọc

* **T7 22/08**: báo cáo model watch. Claude đã ghi sẵn 3 điểm cần soi + cảnh báo
  "sửa cái này sẽ làm đỏ test nào".
* **2-3 đêm nữa**: sync phải xuống < ~10 phút. Không teo thì mổ bước heal, hoặc
  nới trần 120 phút của task (nghi phạm chính khiến đêm tự động chưa lần nào
  chạy tới brief).
* **Vài tuần**: #32 tự chứng minh bằng lệnh live (nhưng xem việc #2 — verdict
  hiện đang bị chấm trên khung ngắn hơn thiết kế).
