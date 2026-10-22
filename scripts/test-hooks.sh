#!/usr/bin/env bash
# Test hành vi của các hook trong .claude/hooks bằng input JSON giống như Claude Code gửi.
# Guard được test với từng cách đọc JSON: auto (jq), python, sed (KIT_JSON_TOOL).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
root="$PWD"
hooks="$root/.claude/hooks"
# shellcheck source=SCRIPTDIR/../.claude/hooks/lib.sh
. "$hooks/lib.sh"
py="$(hook_python)"

fails=0
pass=0
ok() { pass=$((pass + 1)); }
bad() {
  printf '✘ %s\n' "$*" >&2
  fails=$((fails + 1))
}
assert() {
  local msg="$1"
  shift
  if "$@"; then ok; else bad "$msg"; fi
}

# bash_input <lệnh> [cwd]: JSON PreToolUse cho tool $TOOL (mặc định Bash). Không có jq/Python thì tự escape.
bash_input() {
  local c="$1" d="${2:-$root}"
  if [ -n "$py" ]; then
    "$py" -c 'import json, sys; print(json.dumps({"hook_event_name": "PreToolUse", "cwd": sys.argv[2], "tool_name": sys.argv[3], "tool_input": {"command": sys.argv[1], "description": "test"}}))' "$c" "$d" "${TOOL:-Bash}"
  elif command -v jq >/dev/null 2>&1; then
    jq -cn --arg c "$c" --arg d "$d" --arg t "${TOOL:-Bash}" '{hook_event_name: "PreToolUse", cwd: $d, tool_name: $t, tool_input: {command: $c, description: "test"}}'
  else
    c="$(printf '%s' "$c" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
    printf '{"hook_event_name":"PreToolUse","cwd":"%s","tool_name":"%s","tool_input":{"command":"%s","description":"test"}}' "$d" "${TOOL:-Bash}" "$c"
  fi
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# cd rồi mới gọi git, không dùng git -C: Git Bash không đổi đường /tmp/... có [ ] sang đường Windows cho
# git.exe, nên git -C "$tmp/a[x]b" báo "cannot change to" và repo không được tạo.
gitc() { (cd "$1" && git -c user.email=t@t -c user.name=t -c commit.gpgsign=false -c core.autocrlf=false "${@:2}"); }
# new_repo <thư mục> <nhánh>
new_repo() {
  mkdir -p "$1"
  gitc "$1" init -q
  gitc "$1" checkout -q -b "$2"
  gitc "$1" commit -q --allow-empty -m init
}
# Mặc định chạy guard trong repo tạm trên nhánh feature, để kết quả không phụ thuộc nhánh của repo kit.
work="$tmp/work"
new_repo "$work" feat/x
on_main="$tmp/main repo"
new_repo "$on_main" main
# Repo ở nhánh chính, đường dẫn có chữ git và push.
odd="$tmp/my git/github/pushy-main"
new_repo "$odd" main
# Repo ở nhánh chính có tên kết thúc bằng \ (giả lập C:\vnstock\ của PowerShell trên Linux).
bsm="$tmp/w\\"
new_repo "$bsm" main
# Repo ở nhánh chính có tên là mẫu glob khớp một repo ở nhánh feature (a[x]b khớp axb).
globm="$tmp/a[x]b"
new_repo "$globm" main
new_repo "$tmp/axb" feat/x
# Repo ở nhánh feature có symlink trỏ vào thư mục con của repo ở main: git -C link/.. chdir theo đường vật lý,
# tức chạy trong repo ở main. Windows (Git Bash) thường không tạo được symlink thật thì bỏ các ca này.
symf="$tmp/sym feat"
new_repo "$symf" feat/x
mkdir -p "$on_main/sub"
ln -s "$on_main/sub" "$symf/link" 2>/dev/null && [ -L "$symf/link" ] || symf=""
# Chiều ngược lại: repo ở main có symlink trỏ vào thư mục con của repo ở feature. cd của shell đi theo đường
# logic, nên cd "$symm/link/.." vào repo ở main dù đường vật lý là repo ở feature.
symm="$tmp/sym main"
new_repo "$symm" main
mkdir -p "$work/sub"
ln -s "$work/sub" "$symm/link" 2>/dev/null && [ -L "$symm/link" ] || symm=""

modes="auto sed"
[ -n "$py" ] && modes="auto python sed"
mode=auto
ask_count=0
nl=$'\n'
# bash 3.2 (macOS) tới 4.2 giữ dấu nháy của chuỗi thay trong "${x//a/"b"}" (ra "b" kèm nháy). BASH_COMPAT=42
# bắt bash 4.3+ làm y như vậy, để máy Linux/Windows cũng bắt được lỗi chỉ lộ ra trên macOS.
bash42=""
# shellcheck disable=SC2016  # biểu thức được bash con mở rộng
[ "$(BASH_COMPAT=42 bash -c 'x=a; printf %s "${x/a/"b"}"' 2>/dev/null)" = '"b"' ] && bash42=42
# RUN=<hàm>: chạy guard qua hàm đó (nofile, nofile50: xem khối "không tạo được file tạm").
expect_guard() {
  local want="$1" cmd="$2" dir="${3:-$work}" inp
  inp="$(bash_input "$cmd" "$dir")"
  [ "$want" = ask ] && [ "$mode" = auto ] && ask_count=$((ask_count + 1))
  check_guard "$want" "$cmd" "$inp" ""
  # Lệnh có dấu nối dòng: guard nối dòng bằng ${x//a/b}, chạy thêm như bash 3.2-4.2.
  case "$mode:$bash42:$cmd" in auto:42:*"\\$nl"* | auto:42:*"\`$nl"*) check_guard "$want" "$cmd" "$inp" 42 ;; esac
}
# check_guard <ask|allow> <lệnh> <input JSON> <BASH_COMPAT cho guard, rỗng là mặc định>
check_guard() {
  local out tag=" [$mode${RUN:+ $RUN}${4:+, BASH_COMPAT=$4}]"
  out="$(printf '%s\n' "$3" | BASH_COMPAT="$4" KIT_JSON_TOOL="$mode" ${RUN:+"$RUN"} "$hooks/guard-irreversible.sh")"
  if [ "$1" = ask ]; then
    case "$out" in *'"permissionDecision":"ask"'*) ok ;; *) bad "guard phải hỏi$tag: $2 → [$out], input: $3" ;; esac
  else
    assert "guard không được chặn$tag: $2 → $out" [ -z "$out" ]
  fi
}

for mode in $modes; do
  while IFS= read -r c; do [ -n "$c" ] && expect_guard ask "$c"; done <<'EOF'
git push --force origin feat/x
git push origin :feat/x
git push -f
git push --force-with-lease origin feat/x
git push origin +feat/x
git push origin main
git push -u origin HEAD:main
git push origin refs/heads/main
git push origin --delete feat/x
git -C /repo push --force origin feat/x
git -c x=y push -f origin x
git commit -m "wip" && git push --force
git reset --hard HEAD~1
git clean -fd
git clean -d -f
git clean --force -d
git clean -x -d -f
rm -rf /
rm -rf ~
rm -rf .
rm -rf *
rm -r ../
rm -rf "$HOME"
rm -rf $HOME/
cd /tmp && rm -Rf $HOME
bash -c "rm -rf /"
if [ -d x ]; then rm -rf ~; fi
time rm -rf ~
wsl rm -rf ~
psql -c "DROP TABLE users;"
npm publish
terraform apply -auto-approve
terraform -chdir=infra apply -auto-approve
kubectl delete pod web-1
kubectl -n prod delete deployment web
kubectl --context prod apply -f k8s/
helm -n prod upgrade web ./chart
vercel deploy --prod
npm run deploy
gh pr merge 12 --squash
EOF

  while IFS= read -r c; do [ -n "$c" ] && expect_guard allow "$c"; done <<'EOF'
git push -u origin feat/x
git push origin feature/main-thing
git push --dry-run origin feat/x
git -C /repo push origin feat/x
git reset --soft HEAD~1
git clean -n
git rm -r --cached .
rm -rf node_modules
rm -rf ./dist build
git commit -m "fix deploy script and drop table support"
kubectl get pods -n prod
terraform plan
npm test
ls -la
EOF

  # Đang ở nhánh chính: mọi `git push` đều phải hỏi, kể cả có redirect, option hay đường dẫn có dấu cách.
  while IFS= read -r c; do [ -n "$c" ] && expect_guard ask "$c" "$on_main"; done <<'EOF'
git push
git push -u origin HEAD
git push origin 2>&1
git push -u origin 2>&1 | tail -3
git push origin > /dev/null
git push -o ci.skip origin
git commit -m "Đổi tên" && git push origin
EOF
  expect_guard ask "git -C \"$on_main\" push origin"
  expect_guard ask "cd \"$on_main\" && git push"
  expect_guard allow "git push"
  expect_guard allow "git push -u origin HEAD 2>&1"

  # PowerShell tool (Windows): cùng tool_input.command, nhưng lệnh xoá và đổi thư mục viết khác.
  while IFS= read -r c; do [ -n "$c" ] && expect_guard ask "$c"; done <<'EOF'
Remove-Item -Recurse -Force C:\
Remove-Item C:\ -Recurse -Force
Remove-Item -Path "C:\" -Recurse
Remove-Item -Recurse -Force C:\*
Remove-Item -Recurse -Force $env:USERPROFILE
Remove-Item -Recurse -Force .\*
Remove-Item -Recurse -Force ..\
rm -r -fo $HOME
ri -r ~\
rd /s /q C:\
rmdir /s /q .
del /s /q *
cd C:\x; Remove-Item -Recurse -Force *
git push --force origin feat/x 2>&1 | Out-String
Remove-Item -Recurse -Force 'C:\'
Remove-Item -Recurse -Force -LiteralPath 'C:\'
Remove-Item -Recurse -Force '.'
Remove-Item -Recurse -Force '*'
Remove-Item -Recurse -Force ..\*
Remove-Item -Recurse -Force $HOME\*
Remove-Item -Recurse -Force "$HOME\*"
Remove-Item -Recurse -Force $HOME/*
Remove-Item -Recurse -Force $env:USERPROFILE\*
Remove-Item -Recurse -Force $env:SystemDrive\*
Remove-Item -Recurse -Force \
Remove-Item -Recurse -Force /
Remove-Item -Recurse:$true -Force C:\
cmd /c rd /s /q C:\
cmd.exe /c rd /s /q C:\
cmd /c del /s /q *
del /s /q C:\*.*
del /S /Q *.*
Remove-Item -Recurse -Force \*
Remove-Item -Recurse -Force /*
Remove-Item \* -Recurse
ri -r -fo /*
del /s /q \*
Remove-Item -Recurse -Force '\*'
cmd /c del /s /q \*
cmd /d /c rd /s /q C:\
Remove-Item -Recurse -Force ${env:USERPROFILE}\*
rmdir /s /q %USERPROFILE%
rd /s /q %USERPROFILE%\*
EOF
  while IFS= read -r c; do [ -n "$c" ] && expect_guard allow "$c"; done <<'EOF'
Remove-Item -Recurse -Force .\dist
Remove-Item -Recurse node_modules
Remove-Item .\build\out.txt
Remove-Item C:\temp\x.txt
Get-ChildItem -Recurse
Remove-Item -Recurse -Force "$env:TEMP\x"
rd /s /q build
del /s /q *.pyc
cmd /c rd /s /q build
EOF
  expect_guard ask "Set-Location \"$on_main\"; git push"
  expect_guard ask "Set-Location -Path \"$on_main\"; git push origin"
  expect_guard ask "Set-Location -PATH \"$on_main\"; git push"
  expect_guard ask "Push-Location \"$on_main\"; git push"
  # popd quay về thư mục cũ, hoặc đường dẫn không resolve được: xét cả thư mục của phiên.
  expect_guard ask "Push-Location \"$work\"; Pop-Location; git push" "$on_main"
  expect_guard ask "pushd \"$work\"; popd; git push" "$on_main"
  # shellcheck disable=SC2016  # $env:REPO là chữ của lệnh PowerShell
  expect_guard ask 'Set-Location $env:REPO; git push' "$on_main"
  # Phiên đang ở nhánh chính: mọi git push đều hỏi, kể cả cd/-C sang repo khác.
  expect_guard ask "cd \"$work\" && git push" "$on_main"
  # Lệnh xuống dòng bằng \ (bash) hoặc ` (PowerShell): nối dòng trước khi so mẫu.
  expect_guard allow $'rm -rf build \\\n  dist'
  expect_guard allow $'rm -rf /tmp/a \\\n  /tmp/b'
  TOOL=PowerShell expect_guard ask $'Remove-Item -Recurse -Force `\n  C:\\'
  expect_guard ask $'rm -rf \\\n  ~'
  # \ cuối dòng trong PowerShell/cmd là đường dẫn, ` cuối dòng trong bash là đóng `...`:
  # lệnh ở dòng sau vẫn phải được xét như một lệnh mới.
  TOOL=PowerShell expect_guard ask $'Set-Location C:\\\nRemove-Item -Recurse -Force *'
  TOOL=PowerShell expect_guard ask $'Set-Location $env:TEMP\\build\\\nRemove-Item -Recurse -Force .\\*'
  TOOL=PowerShell expect_guard ask $'cd /d C:\\\nrd /s /q .'
  TOOL=PowerShell expect_guard ask $'dir C:\\\ndel /s /q *'
  TOOL=PowerShell expect_guard ask $'cd C:\\\r\nRemove-Item -Recurse -Force *'
  expect_guard ask $'cd `mktemp -d`\nrm -rf *'
  expect_guard ask $'x=`pwd`\nrm -rf ~'
  TOOL=PowerShell expect_guard ask $'Write-Host done `\nRemove-Item -Recurse -Force C:\\'
  TOOL=PowerShell expect_guard ask $'Get-ChildItem C:\\\ndropdb prod'
  TOOL=PowerShell expect_guard ask $'Get-ChildItem C:\\\nnpm run deploy'
  TOOL=PowerShell expect_guard ask $'Remove-Item -Recurse -Force \\\nWrite-Host done'
  TOOL=PowerShell expect_guard ask $'rd /s /q \\\necho done'
  expect_guard ask $'echo hi\nrm -rf /'
  TOOL=PowerShell expect_guard ask "$(printf 'Get-ChildItem C:\\\nSet-Location "%s"\ngit push' "$on_main")"
  # cd đứng SAU git push không được đổi thư mục mà push được xét, kể cả khi lệnh có dấu nối dòng.
  expect_guard ask "$(printf 'git push\ncd "%s" && ls \\\n  -la' "$work")" "$on_main"
  expect_guard ask "$(printf 'git push origin \\\n  HEAD\ncd "%s"' "$work")" "$on_main"
  TOOL=PowerShell expect_guard ask "$(printf 'git push\nSet-Location "%s"\nGet-ChildItem `\n  -Force' "$work")" "$on_main"
  TOOL=Unknown expect_guard ask "$(printf 'git push\ncd "%s" && ls \\\n  -la' "$work")" "$on_main"
  # Dấu nối nằm giữa cd/git -C và đường dẫn: vẫn phải tìm ra thư mục.
  expect_guard ask "$(printf 'cd \\\n  "%s" && git push' "$on_main")"
  expect_guard ask "$(printf 'git -C \\\n  "%s" push' "$on_main")"
  expect_guard ask "$(printf 'pushd \\\n "%s"; git push' "$on_main")"
  TOOL=PowerShell expect_guard ask "$(printf 'git -C `\n "%s" push' "$on_main")"
  TOOL=PowerShell expect_guard ask "$(printf 'Set-Location `\n "%s"\ngit push' "$on_main")"
  # -C của lệnh git KHÁC không đổi thư mục của git push.
  expect_guard ask "git -C \"$work\" fetch && git push" "$on_main"
  expect_guard ask "$(printf 'git -C "%s" status\ngit push' "$work")" "$on_main"
  expect_guard ask "git push && git -C \"$work\" log -1" "$on_main"
  expect_guard ask "git -C \"$work\" push" "$on_main"
  # Đường dẫn chứa chữ git/push, nhiều lệnh push, git log --grep=push: không được đánh lừa.
  expect_guard ask "git -C \"$odd\" push"
  expect_guard ask "git -C \"$on_main\" push && git -C \"$work\" push"
  expect_guard ask "git -C \"$on_main\" push; git push"
  expect_guard ask "git -C \"$on_main\" push && git log --grep=push"
  expect_guard ask "git push && cd \"$work\" && git push" "$on_main"
  expect_guard ask "cd \"$odd\" && git push"
  # Đường dẫn không được bị glob thành thư mục khác.
  expect_guard ask "cd \"$globm\" && git push"
  expect_guard ask "git -C \"$globm\" push"
  if [ -n "$symf" ]; then
    expect_guard ask "git -C link/.. push" "$symf"
    expect_guard ask "git --git-dir=link/../.git push" "$symf"
    expect_guard ask "GIT_DIR=link/../.git git push" "$symf"
  fi
  if [ -n "$symm" ]; then
    expect_guard ask "cd \"$symm/link/..\" && git push"
    expect_guard ask "pushd \"$symm/link/..\"; git push"
  fi
  expect_guard allow "cd \"$work\" && git push origin HEAD"
  expect_guard allow "git -C \"$work\" push -u origin feat/x"
  # cd ở đầu lệnh kiểu khác, cd có option, --git-dir/--work-tree/GIT_DIR, đích chưa xác định.
  expect_guard ask "bash -c 'cd \"$on_main\" && git push'"
  expect_guard ask "{ cd \"$on_main\" && git push; }"
  expect_guard ask "if cd \"$on_main\"; then git push; fi"
  expect_guard ask "cd -- \"$on_main\" && git push"
  expect_guard ask "cd -P \"$on_main\" && git push"
  expect_guard ask "$(printf 'cd %s && git push' "${on_main// /\\ }")"
  expect_guard ask "git --git-dir=\"$on_main/.git\" --work-tree=\"$on_main\" push"
  expect_guard ask "git --git-dir \"$on_main/.git\" push"
  expect_guard ask "GIT_DIR=\"$on_main/.git\" git push"
  expect_guard ask "env --chdir=\"$on_main\" git push"
  expect_guard ask "$(printf 'git -C %s push' "${on_main// /\\ }")"
  expect_guard ask "$(printf 'git -C %s push --force origin x' "${work// /\\ }")"
  # shellcheck disable=SC2016  # $X, `...` là chữ của lệnh được xét
  expect_guard ask 'X=/somewhere; cd $X && git push'
  # shellcheck disable=SC2016
  expect_guard ask 'cd `cat /tmp/dir` && git push'
  # shellcheck disable=SC2016
  expect_guard ask 'git -C "$REPO" push'
  TOOL=PowerShell expect_guard ask "Set-Location -Path:\"$on_main\"; git push"
  TOOL=PowerShell expect_guard ask "Set-Location -PassThru \"$on_main\"; git push"
  # PowerShell không escape bằng \: C:\x\; và C:\x\ push là đường dẫn rồi tới lệnh khác.
  TOOL=PowerShell expect_guard ask "Set-Location $bsm; git push"
  TOOL=PowerShell expect_guard ask "cd $bsm ; git push"
  TOOL=PowerShell expect_guard ask "cd $bsm&& git push"
  TOOL=PowerShell expect_guard ask "git -C $bsm push"
  TOOL=PowerShell expect_guard ask "git -C $bsm push origin HEAD"
  TOOL=Unknown expect_guard ask "Set-Location $bsm; git push"
  TOOL=PowerShell expect_guard ask 'git -C \ push -f'
  expect_guard allow "cd -- \"$work\" && git push"
  expect_guard allow "bash -c 'cd \"$work\" && git push'"
  # Biến quen thuộc thì biết thư mục: $PWD là thư mục của phiên, $CLAUDE_PROJECT_DIR có trong môi trường hook.
  # shellcheck disable=SC2016
  expect_guard allow 'git -C "$PWD" push'
  # shellcheck disable=SC2016
  CLAUDE_PROJECT_DIR="$work" expect_guard allow 'cd "$CLAUDE_PROJECT_DIR" && git push'
  # shellcheck disable=SC2016
  CLAUDE_PROJECT_DIR="$on_main" expect_guard ask 'cd "$CLAUDE_PROJECT_DIR" && git push'
  # \\ cuối dòng là dấu \ thật, không phải dấu nối; PowerShell lồng trong Bash vẫn nối bằng `.
  expect_guard ask $'echo \\\\\nrm -rf \\\n  ~'
  expect_guard ask $'echo \\\\\nnpm \\\n run deploy'
  expect_guard ask $'pwsh -c \'Remove-Item -Recurse -Force `\n C:\\\''
  # Không rõ tool: so trên mọi dạng, thà hỏi thừa.
  TOOL=Unknown expect_guard ask $'Remove-Item -Recurse -Force \\\nWrite-Host done'
  TOOL=Unknown expect_guard ask $'Set-Location C:\\\nRemove-Item -Recurse -Force *'
  TOOL=Unknown expect_guard ask $'Remove-Item -Recurse -Force `\n  C:\\'
done
# Lệnh dài hơn pipe buffer (64 KiB), phần nguy hiểm ở dòng đầu: grep -q thoát ở dòng khớp đầu
# tiên, printf còn ghi dở thì chết vì SIGPIPE, pipefail từng biến "khớp" thành "không khớp".
# Lệnh ~180 KiB, hơn hai lần pipe buffer: grep đọc một lần (tối đa 64 KiB) rồi thoát, printf chỉ
# kịp ghi thêm 64 KiB nữa, nên chắc chắn còn ghi dở. Dưới 128 KiB thì bỏ sót chỉ là may rủi.
# JSON dựng thẳng bằng printf vào file: lệnh dài quá giới hạn đối số (Windows ~32K ký tự).
# long_input <dòng đầu> <cwd> [cuối mỗi dòng, viết dạng JSON]: dòng đầu, rồi 12000 dòng `echo line-N`.
long_input() {
  printf '{"hook_event_name":"PreToolUse","cwd":"%s","tool_name":"Bash","tool_input":{"command":"%s' "$2" "$1"
  # shellcheck disable=SC2059  # phần cuối dòng ghép vào định dạng
  printf "${3:-}"'\\necho line-%s' {1..12000}
  printf '","description":"test"}}\n'
}
long_input 'npm run deploy' "$work" > "$tmp/long-deploy.json"
long_input 'git push' "$on_main" > "$tmp/long-push.json"
# Mọi dòng kết thúc bằng \ nối dòng: guard nối dòng trên cả lệnh (bash 3.2 từng mất ~50 giây với lệnh 15 KB).
long_input 'npm run deploy' "$work" ' \\\\' > "$tmp/long-cont.json"
# Claude Code dừng hook chạy quá timeout trong settings.json rồi cho lệnh chạy mà KHÔNG hỏi, nên guard
# chạy với đúng giới hạn đó (cần perl; không có thì không giới hạn). macOS từng mất hàng phút ở đây.
guard_timeout="$(awk '/guard-irreversible\.sh/ { f = 1 } f && match($0, /"timeout"[ \t]*:[ \t]*[0-9]+/) {
  t = substr($0, RSTART, RLENGTH); gsub(/[^0-9]/, "", t); print t; exit }' "$root/.claude/settings.json" 2>/dev/null)"
guard_timeout="${guard_timeout:-10}"
# Dừng cả nhóm tiến trình: grep hay sed con còn chạy sẽ giữ stdout, $(...) phải đợi nó.
hook_limit() {
  command -v perl >/dev/null 2>&1 || { "$@"; return; }
  perl -e '$t = shift; $p = fork; defined $p or die "fork: $!";
    if (!$p) { setpgrp(0, 0); exec @ARGV or exit 127 }
    $SIG{ALRM} = sub { kill "KILL", -$p; waitpid $p, 0; exit 142 };
    alarm $t; waitpid $p, 0; exit($? & 127 ? 128 + ($? & 127) : $? >> 8)' "$guard_timeout" "$@"
}
for mode in $modes; do
  for f in long-deploy long-push long-cont; do
    out="$(KIT_JSON_TOOL="$mode" hook_limit "$hooks/guard-irreversible.sh" < "$tmp/$f.json")"
    case "$out" in
      *'"permissionDecision":"ask"'*) ok ;;
      *) bad "guard phải hỏi trong ${guard_timeout} giây [$mode]: lệnh dài hơn pipe buffer ($(wc -c < "$tmp/$f.json") byte, input: $(head -c 160 "$tmp/$f.json")...) → [$out]" ;;
    esac
  done
done
# Tiến trình cha bỏ qua SIGPIPE (trap '' PIPE, kế thừa sang con): printf không chết mà báo lỗi ghi
# ra stderr. Kết quả đã theo mã của grep, nên vẫn phải hỏi và stderr phải sạch.
for mode in $modes; do
  out="$( (trap '' PIPE; KIT_JSON_TOOL="$mode" hook_limit "$hooks/guard-irreversible.sh" < "$tmp/long-deploy.json") 2>"$tmp/sigpipe.err")"
  case "$out" in
    *'"permissionDecision":"ask"'*) ok ;;
    *) bad "guard phải hỏi [$mode] khi SIGPIPE bị bỏ qua: lệnh dài hơn pipe buffer → [$out]" ;;
  esac
  assert "guard không được in ra stderr [$mode] khi SIGPIPE bị bỏ qua → $(cat "$tmp/sigpipe.err")" [ ! -s "$tmp/sigpipe.err" ]
done
# Bash không tạo được file tạm (đĩa đầy, TMPDIR không ghi được): here-doc báo "cannot create temp
# file", vòng đọc nó không chạy lần nào, git push trên nhánh chính từng lọt qua im lặng. Bash < 5.1
# luôn ghi here-doc ra file tạm, bash ≥ 5.1 khi here-doc lớn hơn pipe buffer (64 KiB trên Linux)
# hoặc BASH_COMPAT=50 (nofile50).
# Giả lập bằng ulimit -f 0, bỏ qua SIGXFSZ để write báo EFBIG thay vì giết tiến trình. Không có
# ulimit -f (Git Bash) thì guard chạy như thường, ca vẫn phải đúng.
nofile() { (trap '' XFSZ; ulimit -f 0 2>/dev/null; "$@"); }
nofile50() { nofile env BASH_COMPAT=50 "$@"; }
# 30 lần cd vào thư mục con tên 200 ký tự: mỗi cd nối dài đường dẫn, danh sách thư mục ~94 KB.
long_cd="$(printf "cd $(printf '%0200d' 0) ; %.0s" {1..30})"
for mode in $modes; do
  RUN=nofile50 expect_guard ask "git push" "$on_main"
  RUN=nofile50 expect_guard ask "cd \"$on_main\" && git push"
  RUN=nofile50 expect_guard ask "git -C \"$on_main\" push"
  RUN=nofile expect_guard ask "${long_cd}git push" "$on_main"
  RUN=nofile50 expect_guard allow "cd \"$work\" && git push origin HEAD"
done
if [ -n "$py" ]; then
  # Windows: Python đọc stdin theo cp1252, chữ "Đ" từng làm hỏng việc đọc lệnh.
  out="$(bash_input 'git commit -m "Đổi tên" && git push origin' "$on_main" \
    | PYTHONIOENCODING=cp1252 KIT_JSON_TOOL=python "$hooks/guard-irreversible.sh")"
  case "$out" in *'"permissionDecision":"ask"'*) ok ;; *) bad "guard phải hỏi khi Python đọc stdin bằng cp1252" ;; esac
fi
mode=auto
# Thư mục của chính tiến trình hook (ở đây: repo đang ở main) không được xen vào việc xét push.
out="$(cd "$on_main" && bash_input "git push" "$work" | "$hooks/guard-irreversible.sh")"
assert "guard không được xét thư mục của tiến trình hook → $out" [ -z "$out" ]

# Stop gate: repo tạm có check.sh giả (xanh khi có file GREEN).
make_repo() {
  mkdir -p "$1/scripts"
  gitc "$1" init -q
  gitc "$1" commit -q --allow-empty -m init
  # shellcheck disable=SC2016
  printf '#!/usr/bin/env bash\n[ -f "$(dirname "$0")/../GREEN" ]\n' > "$1/scripts/check.sh"
  chmod +x "$1/scripts/check.sh"
  gitc "$1" add scripts
  gitc "$1" commit -q -m check
}
repo="$tmp/stop"
make_repo "$repo"
session="test-$$-$RANDOM"
stop_input() { printf '{"hook_event_name":"Stop","session_id":"%s","cwd":"%s","stop_hook_active":false}' "$session" "$1"; }
run_stop() { stop_input "${1:-$repo}" | AGENT_STOP_GATE_MAX=2 "$hooks/stop-gate.sh" 2>/dev/null; }
# Chặn = JSON {"decision":"block"} với exit 0, hoặc exit 2 khi không có jq/Python.
blocked() {
  [ "$code" -eq 2 ] || { [ "$code" -eq 0 ] && text_grep "$out" -q '"decision": *"block"'; }
}

out="$(run_stop)"; code=$?
assert "stop-gate: không có thay đổi thì phải cho dừng (exit $code)" [ "$code" -eq 0 ]
assert "stop-gate: không có thay đổi thì không in gì" [ -z "$out" ]

echo "ghi chú" > "$repo/NOTES.md"
echo "ghi chú" > "$repo/ghi-chú.md"
out="$(run_stop)"; code=$?
assert "stop-gate: chỉ đổi file .md (kể cả tên có dấu) thì không chạy check (exit $code)" [ "$code" -eq 0 ]
assert "stop-gate: chỉ đổi file .md thì không in gì" [ -z "$out" ]

echo "x" > "$repo/app.js"
out="$(run_stop)"; code=$?
assert "stop-gate: check đỏ thì phải chặn (exit $code)" blocked
case "$out" in *"1/2)"*) ok ;; *) bad "stop-gate: lý do chặn phải ghi số lần chặn → $out" ;; esac
out="$(run_stop)"; code=$?
assert "stop-gate: lần chặn thứ 2 vẫn phải chặn (exit $code)" blocked
out="$(run_stop)"; code=$?
if [ "$code" -eq 0 ] && text_grep "$out" -q systemMessage; then ok; else bad "stop-gate: quá giới hạn thì nhả kèm systemMessage (exit $code)"; fi

# Bộ đếm phải về 0 khi không còn thay đổi: chặn 1 lần, bỏ thay đổi, rồi đỏ lại → bắt đầu từ 1.
run_stop >/dev/null
rm "$repo/app.js"
run_stop >/dev/null
echo "x" > "$repo/app.js"
out="$(run_stop)"; code=$?
case "$out" in *"1/2)"*) ok ;; *) bad "stop-gate: hết thay đổi thì bộ đếm phải về 0 → $out" ;; esac

touch "$repo/GREEN"
out="$(run_stop)"; code=$?
assert "stop-gate: check xanh thì cho dừng (exit $code)" [ "$code" -eq 0 ]
assert "stop-gate: check xanh thì không in gì" [ -z "$out" ]
rm "$repo/GREEN"

out="$(stop_input "$repo" | AGENT_STOP_GATE=off "$hooks/stop-gate.sh")"; code=$?
assert "stop-gate: AGENT_STOP_GATE=off phải cho dừng" [ "$code" -eq 0 ]

# cwd không tồn tại: dừng ngay, không đoán sang thư mục hiện tại (từng gây đệ quy vào check của repo kit).
out="$(stop_input "$tmp/khong-ton-tai" | AGENT_STOP_GATE_MAX=2 "$hooks/stop-gate.sh" 2>&1)"; code=$?
assert "stop-gate: cwd không tồn tại thì cho dừng (exit $code)" [ "$code" -eq 0 ]
assert "stop-gate: cwd không tồn tại thì không chạy check → $out" [ -z "$out" ]

# check.sh gọi lại stop gate trên chính repo đó: lần lồng phải bỏ qua, không đệ quy.
rec="$tmp/rec repo"
make_repo "$rec"
cat > "$rec/scripts/check.sh" <<EOF
#!/usr/bin/env bash
n=\$(( \$(cat "$rec/.count" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "$rec/.count"
if [ "\$n" -lt 5 ]; then
  printf '{"session_id":"rec-inner","cwd":"%s"}' "$rec" | "$hooks/stop-gate.sh" >/dev/null 2>&1
fi
exit 1
EOF
out="$(printf '{"session_id":"rec-%s","cwd":"%s"}' "$$" "$rec" | AGENT_STOP_GATE_MAX=9 "$hooks/stop-gate.sh" 2>/dev/null)"; code=$?
assert "stop-gate: check.sh gọi lại stop gate thì chỉ chạy check 1 lần → $(cat "$rec/.count")" [ "$(cat "$rec/.count")" = 1 ]
assert "stop-gate: lần ngoài vẫn phải chặn (exit $code)" blocked

session="test-$$-$RANDOM"
out="$(stop_input "$repo" | KIT_JSON_TOOL=sed AGENT_STOP_GATE_MAX=9 "$hooks/stop-gate.sh" 2>/dev/null)"; code=$?
assert "stop-gate: không có jq/Python thì chặn bằng exit 2 (exit $code)" [ "$code" -eq 2 ]

if [ -n "$py" ]; then
  # Máy không có jq (Windows): JSON chặn do Python in, phải parse được và giữ đủ lý do.
  session="test-$$-$RANDOM"
  out="$(stop_input "$repo" | KIT_JSON_TOOL=python AGENT_STOP_GATE_MAX=9 "$hooks/stop-gate.sh" 2>/dev/null)"; code=$?
  reason="$(printf '%s' "$out" | "$py" -c 'import json, sys; d = json.loads(sys.stdin.read()); sys.stdout.buffer.write((d["decision"] + "|" + d["reason"]).encode("utf-8"))' 2>/dev/null)"
  case "$reason" in "block|"*"lần chặn 1/9"*) ok ;; *) bad "stop-gate qua Python: JSON chặn phải parse được, có lý do → $out" ;; esac
fi

# Commit cục bộ trên nhánh chưa có upstream vẫn là thay đổi chưa push → phải chạy check.
remote="$tmp/remote.git"
git init -q --bare "$remote"
feat="$tmp/feat"
make_repo "$feat"
gitc "$feat" remote add origin "$remote"
gitc "$feat" push -q origin HEAD:refs/heads/main >/dev/null 2>&1
gitc "$feat" checkout -q -b feat/x
echo "x" > "$feat/app.js"
gitc "$feat" add app.js
gitc "$feat" commit -q -m "feat: app"
session="test-$$-$RANDOM"
out="$(run_stop "$feat")"; code=$?
assert "stop-gate: commit chưa push trên nhánh không có upstream phải bị chặn khi check đỏ (exit $code)" blocked
gitc "$feat" push -q -u origin feat/x >/dev/null 2>&1
session="test-$$-$RANDOM"
out="$(run_stop "$feat")"; code=$?
assert "stop-gate: đã push hết thì cho dừng (exit $code)" [ "$code" -eq 0 ]

# Sàn số ca "phải hỏi": được thêm, không được bớt. Bớt ca để guard dễ dãi hơn phải là quyết định
# của người, sửa scripts/guard-ask-floor trong cùng thay đổi để người review thấy.
floor_file="$root/scripts/guard-ask-floor"
if [ -f "$floor_file" ]; then
  floor="$(tr -dc '0-9' < "$floor_file")"
  if [ "$ask_count" -lt "${floor:-0}" ]; then
    bad "số ca 'phải hỏi' giảm còn $ask_count, dưới sàn ${floor} trong scripts/guard-ask-floor"
  else
    ok
    [ "$ask_count" -gt "${floor:-0}" ] && printf '• guard: %s ca phải hỏi, có thể nâng scripts/guard-ask-floor lên %s\n' "$ask_count" "$ask_count"
  fi
fi

# Post-edit format: không bao giờ chặn, kể cả khi file không tồn tại.
for f in "$tmp/khong-ton-tai.ts" "$repo/app.js" "$repo/NOTES.md"; do
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$f" | "$hooks/post-edit-format.sh"
  code=$?
  assert "post-edit-format phải luôn exit 0 ($f)" [ "$code" -eq 0 ]
done

if [ "$fails" -gt 0 ]; then
  printf '✘ hooks: %s/%s test đỏ\n' "$fails" "$((fails + pass))" >&2
  exit 1
fi
printf '✔ hooks: %s test xanh\n' "$pass"
