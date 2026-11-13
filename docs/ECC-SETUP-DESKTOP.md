# Cài ECC (Everything Claude Code) trên desktop Windows

Hướng dẫn tái tạo đúng setup ECC đã làm ngày 21/07/2026 (PR #14) trên máy
desktop `C:\vnstock`. Setup gồm 2 tầng:

- **Project-level** (`.claude/skills` + `.claude/rules` trong repo): đã nằm
  trong `main` — chỉ cần `git pull`.
- **User-level** (`C:\Users\Administrator\.claude\skills`): bộ skill core
  dùng chung mọi project — phải cài riêng trên từng máy (bước 2).

---

## Bước 1 — Pull phần project-level từ repo

```powershell
cd C:\vnstock
git pull origin main
```

Sau bước này repo đã có:

- `.claude/skills/`: python-patterns, python-testing, iterative-retrieval (bản mới)
  + các skill có sẵn từ trước.
- `.claude/rules/`: python (5) + `agent-team.md`. `rules/common` (10 file luật chung của ECC) đã gỡ
  13/11 theo quyết định của user: nạp vào MỌI phiên mà nhiều điều không làm được ở repo này (gọi agent
  `planner`/`tdd-guide` không tồn tại, coverage 80% khi repo không đo, đặt tên camelCase cho dự án
  Python). Luật thật của dự án ở `CLAUDE.md` + `rules/agent-team.md`.
- Đã gỡ 13/11 vì repo không có ngăn xếp tương ứng (0 file .ts/.go/.kt/.rs/.cpp/
  .dart/.java, không FastAPI/Postgres/ClickHouse/JPA): rules `typescript`,
  `golang`, `python/fastapi.md`; skill `postgres-patterns`, `clickhouse-io`,
  `jpa-patterns`, `windows-desktop-e2e`; 24 lệnh `/cpp-*`, `/flutter-*`,
  `/go-*`, `/gradle-build`, `/kotlin-*`, `/react-*`, `/rust-*`,
  `/fastapi-review`, `/pm2`, `/setup-pm`, `/jira`, `/marketing-campaign`.
  Gỡ cùng đợt: skill `continuous-learning` (v1) — chính nó tự ghi DEPRECATED, "Do not invoke v1".
  Gỡ tiếp 13/11: skill `continuous-learning-v2` + 7 lệnh của nó (`/evolve`, `/instinct-status`,
  `/instinct-import`, `/instinct-export`, `/projects`, `/promote`, `/prune`) — hook quan sát chưa từng
  được nối trong `.claude/settings.json`, và `instinct-cli.py status` trên 🖥️ desktop trả
  "No instincts found" (kho `~\.local\share\ecc-homunculus` trống) ⇒ hệ thống chưa từng học được gì.
  Cập nhật ECC từ upstream thì ĐỪNG chép lại các mục này.
- Fix `datetime.utcnow()` trong 7 module + số liệu test mới trong CLAUDE.md.

## Bước 2 — Cài bộ skill core user-level

### Cách A — Dùng wizard (khuyên dùng)

Mở Claude Code trong `C:\vnstock` và gõ:

```
/configure-ecc
```

Khi wizard hỏi, chọn:

1. **Installation level**: `User-level (~/.claude/)` — phần project-level đã
   có trong repo rồi, KHÔNG chọn Both/Project để tránh ghi đè.
2. **Skill scope**: `Core only` — các skill niche (python-patterns,
   python-testing…) đã nằm trong repo.
3. **Rules**: bỏ qua (không cài) — rules đã có trong `.claude/rules/`.

### Cách B — Chạy tay bằng PowerShell

```powershell
# 1. Clone ECC mới nhất vào thư mục tạm
$ecc = "$env:TEMP\everything-claude-code"
Remove-Item -Recurse -Force $ecc -ErrorAction SilentlyContinue
git clone --depth 1 https://github.com/affaan-m/everything-claude-code.git $ecc

# 2. Copy bộ core (.agents/skills/*) vào ~/.claude/skills
$target = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force $target | Out-Null

Get-ChildItem "$ecc\.agents\skills" -Directory | ForEach-Object {
    $dest = Join-Path $target $_.Name
    # Xóa bản cũ trước — nếu không Copy-Item sẽ lồng thư mục vào trong
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item $_.FullName -Destination $dest -Recurse
}

# 3. Thêm 2 skill bổ sung ngoài bộ core
foreach ($s in "search-first", "videodb") {
    $dest = Join-Path $target $s
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item "$ecc\skills\$s" -Destination $dest -Recurse
}

# 4. Dọn thư mục tạm
Remove-Item -Recurse -Force $ecc
```

⚠️ Gotcha đã gặp khi cài lần đầu: nếu thư mục đích đã tồn tại,
`Copy-Item`/`cp -R` sẽ copy LỒNG source vào bên trong thay vì ghi đè
(ra `skill-x\skill-x\SKILL.md`). Script trên đã xử lý bằng cách xóa đích
trước khi copy.

## Bước 3 — Kiểm tra

```powershell
# Mỗi skill phải có SKILL.md ở cấp 1 (không bị lồng)
Get-ChildItem "$env:USERPROFILE\.claude\skills" -Directory |
    Where-Object { -not (Test-Path (Join-Path $_.FullName "SKILL.md")) }
# → danh sách rỗng = OK
```

Sau đó **khởi động lại Claude Code** (bắt buộc để nạp rules mới), rồi thử:

- `/python-testing` → phải hiện phần "Project: vnstock-dashboard" (chạy test
  qua `run.py`, quy tắc guard + test).
- `/tdd-workflow` → skill core user-level hoạt động.

Cuối cùng chạy test để chốt mọi thứ xanh:

```powershell
& "C:\Users\Administrator\.venv\Scripts\Activate.ps1"
python run.py test    # kỳ vọng ~2.228 pass, không còn warning utcnow
```

## Ghi chú

- Bộ core user-level áp dụng cho MỌI project trên desktop, không riêng
  vnstock. Muốn cập nhật lên bản ECC mới hơn: chạy lại Bước 2 (script đã
  ghi đè an toàn).
- Rules trong `.claude/rules/` nạp tự động theo pattern file (ví dụ sửa
  `.py` → rules python); không cần cài gì thêm.
- Skill `python-testing`/`python-patterns` trong repo đã được tùy biến theo
  quy trình vnstock — khi update từ ECC upstream, đừng ghi đè mất phần
  "Project: vnstock-dashboard" ở đầu file.
