# ✅ VIỆC ĐANG LÀM — trang DUY NHẤT cần mở

> Đây là bản để LÀM THEO. Kho lưu chi tiết (lý do, file:line, lịch sử) nằm ở
> `docs/CLAUDE-NOTES.md` — đừng mở nó để biết "hôm nay làm gì".
> Cập nhật: 19/08/2026.

## 🏷️ NHÃN MÁY — mọi việc trong file này BẮT BUỘC có một nhãn

| Nhãn | Nghĩa |
|---|---|
| 🖥️ **DESKTOP** | Chỉ chạy được trên máy chạy pipeline (có 2 task lịch). Laptop không có log / task / kho được cập nhật đêm. |
| 💻 **LAPTOP** | Chỉ nên làm trên laptop (thường là thử nghiệm rủi ro — hỏng cũng không mất brief đêm). |
| ⇄ **CẢ HAI** | Phải làm **lặp lại trên từng máy** — dành cho thứ KHÔNG nằm trong kho (venv, thư viện pip, task lịch, biến môi trường). **Việc chữa KHO thì KHÔNG thuộc nhóm này**: `C:\vnstock` đồng bộ qua Dropbox nên làm một máy là xong cả hai (sửa 19/08, trước đó ghi sai). |
| ○ **MÁY NÀO CŨNG ĐƯỢC** | Kết quả như nhau ở đâu cũng vậy (chạy test, đọc code). |

**Xác định đang ngồi máy nào** (2 giây, làm trước mọi thứ — đừng đoán bằng
đường dẫn `C:\vnstock` hay tên venv, hai máy cài giống hệt nhau, đã nhầm 19/08):

```powershell
$env:COMPUTERNAME; Get-ScheduledTask -TaskName 'VnStock *' | Select-Object TaskName
```
Ra 2 task = **desktop**. Rỗng = **laptop** (`CFA-BINHLD-LT`).

---

## 📍 ĐIỂM DỪNG 19/08/2026 — mở lại thì đọc 10 dòng này trước

Commit cuối của Claude: **`ff7e0ee`**. Nhánh
`claude/tong-hop-cong-viec-test-w8mvrc`. Suite **2.263 passed** (fast 1.743).
Máy user đang ở `main` → lấy code phải `git fetch origin <nhánh> && git merge
origin/<nhánh>` (`git pull` báo "Already up to date" dù vừa tải commit về).

| Việc | Trạng thái |
|---|---|
| Chữa lệch cơ sở (kho DÙNG CHUNG, làm 1 lần) | ghi 70/70 trên laptop · quét lại **68 sạch, còn VTP + QNS** · code đã vá, chạy lại 2 mã bằng bản mới ở máy nào cũng được |
| Trần task Daily `PT180M` — 🖥️ desktop | **chưa xác nhận** · cần PowerShell Administrator |
| Chạy lại backtest/kiểm định | **chưa** · chỉ chạy sau khi kho về 0 mã lệch. Mọi verdict trước 19/08 (kể cả #32 p=0.012) coi như VÔ HIỆU |
| V1 — guard chặn tái phát | ✅ **XONG 19/08** (`vnstock_basis_guard.py`, 19 test) — cửa gác nằm ở đúng đường ghi chính, có badge doctor + kill-switch |

**✅ ĐÃ GIẢI — DROPBOX, không phải chép tay.** `C:\vnstock` vẫn được Dropbox
đồng bộ giữa desktop `PICHU` và laptop `CFA-BINHLD-LT` (user xác nhận 19/08).
77 thư mục `_meta/backup_rebase` có TÊN đóng dấu 15:43–15:48 nhưng
`CreationTime` 17:39 vì đó là lúc Dropbox **tải chúng xuống** desktop. Cùng lý
do: 25.940 file khác giữ ngày tạo cũ — chúng không đổi nên Dropbox không tải
lại. Lượt chữa 70 mã chạy trên laptop và tự có mặt trên desktop.

🔴 **Ghi chú cũ trong `CLAUDE.md` ("đã bỏ Dropbox, hai kho ĐỘC LẬP") là SAI** —
chính nó làm Claude quy sai máy và gán nhãn ⇄ CẢ HAI cho mọi việc chữa kho
suốt ngày 19/08. Đã sửa. **Chữa kho làm MỘT LẦN là đủ.**

⚠️ Đổi lại: marker và badge cũng đi theo kho. `test_status.json` /
`doctor_status.json` không có trường máy nên badge sidebar có thể là kết quả
của MÁY KIA; `brief_push.json` chạy ở laptop là desktop câm brief tối đó.
Và **đừng đụng kho ở máy kia trong lúc pipeline chạy** — hai bên ghi cùng file
là Dropbox sinh "conflicted copy" nằm ngay trong `prices/`, mà `load_bars`
glob `year=*/*.parquet` sẽ đọc luôn file đó.

✅ **Sổ lệnh KHÔNG mất.** `brief_memory.db`: 805 briefs · 148 rec · 138
outcome, brief cuối `2026-08-18T23:16:05` — đúng bản desktop gửi tay tối
18/08. Nhưng nhớ dài hạn: đây là nơi DUY NHẤT giữ sổ lệnh + outcome + verdict
kiểm định và **không module nào backup nó**.

**Lệnh đầu tiên khi quay lại (○ máy nào cũng được — kho dùng chung):**

```powershell
git fetch origin claude/tong-hop-cong-viec-test-w8mvrc
git merge origin/claude/tong-hop-cong-viec-test-w8mvrc
python scripts\rebase_ticker_history.py --ticker VTP --ticker QNS --apply
python scripts\probe_price_basis.py --sweep      # kỳ vọng: 0 mã
```

---

## 🔴 VIỆC CỦA BẠN

### ○ MỘT MÁY LÀ ĐỦ · 🔥 SỐ 1 — Chữa nốt VTP + QNS

Quét 19/08: **70/159 mã thanh khoản lệch cơ sở**, gần trọn VN30, vách rải
03–08/2026 (mùa chia cổ tức). Đã chạy `--apply` trên laptop lúc 15:43 → ghi
70/70; Dropbox đưa sang desktop, quét lại 17:45 trên desktop ra **68 sạch**.

**Còn đúng 2 mã: VTP `0.8521×` · QNS `0.9785×`** (cùng vách 2026-03-17). Hai
mã này bị nguồn rebase HAI lần nên có hai bậc; bản cũ chữa tới ngày vách là bỏ
sót lớp giữa, và tự kiểm cũ chỉ soi vách giá ≥30% nên vẫn in ✅. Cả hai lỗi đã
vá (`7fcfe88`) — **chạy lại lệnh cũ y nguyên sẽ không đổi gì**, phải lấy code
mới trước.

Kho dùng chung nên **chạy ở máy nào cũng được, một lần**. Đừng chạy song song
hai máy. Nếu chạy trên desktop thì phải đợi pipeline đêm xong.

```powershell
git fetch origin claude/tong-hop-cong-viec-test-w8mvrc
git merge origin/claude/tong-hop-cong-viec-test-w8mvrc

python scripts\rebase_ticker_history.py --ticker VTP --ticker QNS --apply
python scripts\probe_price_basis.py --sweep      # kỳ vọng: 0 mã
```

*Vết quét `_meta/basis_sweep_check.json` cũng nằm TRONG kho nên nó đồng bộ —
không cần quét lại ở máy thứ hai. (Ghi chú cũ bảo "phải quét lại trước vì file
local từng máy" là SAI, sửa 19/08.)*

**An toàn:** mỗi mã tự sao lưu vào `_meta/backup_rebase/<MÃ>_<timestamp>/`
trước khi ghi, ghi nguyên tử, tự kiểm sau khi ghi — tự kiểm fail thì mã đó tự
khôi phục.

**Sai số đã chấp nhận có ý thức:** PET (thưởng, factor 1.4499 vs bước 0.43) và
F88 (chia tách 2.0000× vs bước 3.08) — bằng chứng khối lượng mâu thuẫn sổ sự
kiện nên công cụ GIỮ khối lượng nguồn. Hệ quả: GTGD lịch sử 2 mã này hụt đúng
bằng factor, chỉ chạm bộ lọc thanh khoản. Ép thủ công:
`--ticker PET --volume adjust`.

### ○ Sau khi chữa xong — 3 lệnh chạy lại (một lần, máy nào cũng được)

```powershell
python run.py test                                    # full suite, kỳ vọng 2.263 passed
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

### 🖥️ DESKTOP · Marker `brief_push.json` — 5 giây, làm sớm

Marker chống gửi trùng nằm TRONG kho nên đi theo Dropbox: laptop lỡ chạy
`run.py telegram close` hôm nào là desktop **câm brief tối đó** mà `cmd_brief`
vẫn `return 0` (pipeline xanh, không ai biết).

```powershell
Get-Content C:\vnstock\data_warehouse\_meta\brief_push.json -Raw
```
Ra ngày HÔM NAY = brief tối nay sẽ bị bỏ qua → đợi pipeline xong rồi gửi tay
bằng `python run.py telegram close --force`. Ra ngày cũ hoặc không có file =
bình thường.

### 🖥️ DESKTOP · Quét "conflicted copy" — sau mỗi lần hai máy cùng động vào kho

Dropbox ghi song song với pipeline ⇒ có thể đẻ `... (conflicted copy).parquet`
NGAY trong `prices/`, mà `load_bars` glob `year=*/*.parquet` sẽ đọc luôn file
đó → bar trùng, lẫn cơ sở. Chưa có guard nào chặn (Claude đang xếp làm).

```powershell
Get-ChildItem -Recurse C:\vnstock\data_warehouse -Filter "*conflicted*" |
  Select-Object FullName, Length, LastWriteTime
```
Ra file nào thì ĐỪNG xoá vội — dán cho Claude, phải xem nó là bản nào trước.

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
| 0 | 🎯 **Mổ `auto-heal`** — ĐÃ ĐO 19/08: sync 43,1' = auto-heal **35,9'** (83%) · updater 5,0' · fix-units 1,6' · rollup 0,5'. Nghi phạm cũ (`fix-units`) SAI. auto-heal gọi mạng theo từng bar cách ly | Chiếm 51% cả phát. Hỏi trước: hàng đợi cách ly bao nhiêu bar, có phải đêm nào cũng thử lại đúng những bar không bao giờ lành? | ~1 buổi |
| ~~1~~ | ✅ **XONG 19/08** (`970a504`) — test hết ghi bẩn `run_daily.log` | Đo lại: chạy full suite xong log không đổi **một byte** | — |
| ~~2~~ | ✅ **XONG 19/08** (`a83ee51`) — rec hết bị đóng sớm; lệnh thủng SL nay nhận ra ngay thay vì chờ hết horizon | Verdict #32 từ nay chấm trên đúng khung | — |
| ~~V1~~ | ✅ **XONG 19/08** — `vnstock_basis_guard`: nới cửa sổ fetch để đối chiếu, lệch >1,2% thì TỪ CHỐI nối + cách ly + badge doctor | Mùa cổ tức sau không lặp lại 70 mã nữa | — |
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
