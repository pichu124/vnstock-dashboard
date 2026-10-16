#!/usr/bin/env bash
# PreToolUse(Bash|PowerShell): buộc hỏi người trước hành động không đảo ngược được.
# Trên Windows, Claude Code chạy lệnh qua PowerShell tool là chính, nên matcher phải gồm cả PowerShell.
# Khớp mẫu thì in permissionDecision "ask". Không khớp thì im lặng cho qua.
# Khớp thừa chỉ tốn một câu hỏi, bỏ sót thì mất dữ liệu, nên các mẫu cố ý bắt rộng.
# Thêm mẫu: gọi thêm một dòng `rule '<regex ERE>' '<lý do>'` ở dưới, và thêm ca vào scripts/test-hooks.sh.
set -uo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

input="$(cat)"
cwd="$(json_get "$input" cwd)"
cmd="$(json_get "$input" tool_input.command)"
# Không đọc được lệnh: so mẫu trên toàn bộ input thô (thà hỏi thừa).
[ -n "$cmd" ] || cmd="$input"
# Nối dòng: bash dùng \ cuối dòng, PowerShell dùng `. Ở tool kia, ký tự đó cuối dòng là thứ
# khác (C:\ trong PowerShell, dấu đóng `...` trong bash), còn \\ là dấu \ thật. grep so từng
# dòng, nên so trên nhiều dạng: nối theo tool (đích nằm ở dòng sau), giữ dòng nhưng bỏ dấu
# nối (lệnh ở dòng sau vẫn là đầu lệnh), nối cả hai kiểu (PowerShell lồng trong bash). Không
# rõ tool thì so thêm bản gốc. Kiểm tra push trên nhánh chính đọc từng dạng riêng ($forms).
nl=$'\n'
tool="$(json_get "$input" tool_name)"
kept="$cmd"
forms=("$cmd")
case "$cmd" in
  *"\\$nl"* | *"\`$nl"*)
    ph=$'\001'
    bs='\'
    case "$tool" in
      Bash) marks='\' ;;
      PowerShell) marks='`' ;;
      *) marks='\`' ;;
    esac
    src="${cmd//"$bs$bs"/"$ph"}"
    joined="$src"
    kept="$src"
    both="$src"
    for ((i = 0; i < ${#marks}; i++)); do
      m="${marks:i:1}"
      joined="${joined//"$m$nl"/" "}"
      kept="${kept//"$m$nl"/"$nl"}"
    done
    both="${both//"$bs$nl"/" "}"
    both="${both//"\`$nl"/" "}"
    joined="${joined//"$ph"/"$bs$bs"}"
    kept="${kept//"$ph"/"$bs$bs"}"
    both="${both//"$ph"/"$bs$bs"}"
    forms=("$kept" "$joined" "$both")
    case "$tool" in
      Bash | PowerShell) cmd="$joined$nl$kept$nl$both" ;;
      *) cmd="$joined$nl$kept$nl$both$nl$cmd" ;;
    esac
    ;;
esac

reason=""
rule() {
  if [ -z "$reason" ] && printf '%s' "$cmd" | grep -Eiq -- "$1"; then
    reason="$2"
  fi
}

S='[[:space:]]'
# Kết thúc một từ: khoảng trắng, dấu nối lệnh, dấu nháy hoặc hết chuỗi.
# shellcheck disable=SC1003  # dấu \ trong bracket là ký tự cần khớp
E='([[:space:];&|)"\'"'"']|$)'
# Option chen giữa tên tool và subcommand: git -C dir, kubectl -n prod, terraform -chdir=infra...
# Giá trị option có thể nằm trong nháy và chứa dấu cách: git -C "C:/my repo" push.
# Giá trị không nháy: đọc theo cả hai cách, \ là ký tự thường (PowerShell: C:\x\) hoặc là escape
# (bash: my\ repo). Regex được chọn cách nào khớp, nên hỏi thừa chứ không bỏ sót.
O='([[:space:]]+-[^[:space:]]+([[:space:]]+("[^"]*"|'"'"'[^'"'"']*'"'"'|[^-[:space:]"'"'"'][^[:space:]]*|([^-[:space:]"'"'"'\\]|\\.)([^[:space:]\\]|\\.)*\\?))?)*' 
# Vị trí bắt đầu một lệnh (để `git rm` không bị coi là `rm`).
B='(^|[;&|(`"'"'"'{]|\$\(|(^|[[:space:]])(then|do|else|time|xargs|exec|nohup|env)[[:space:]])[[:space:]]*((sudo|doas|wsl)[[:space:]]+)?'
G="git${O}${S}+"
MAIN='(main|master|trunk|production|release)'
# shellcheck disable=SC2016  # $HOME ở đây là ký tự cần khớp, không phải biến
RMT='"?(/|/\*|~/?|~/\*|\$HOME/?|\$\{HOME\}/?|\.|\./|\.\.|\.\./|\*|\./\*)"?'

rule "${G}push[^;&|]*${S}(-f|--force|--force-with-lease|--force-if-includes|--mirror|--delete|-d)${E}" "force-push hoặc xoá nhánh remote"
rule "${G}push[^;&|]*${S}\+[^[:space:]]" "force-push bằng refspec +"
rule "${G}push[^;&|]*${S}:[^[:space:]]" "xoá nhánh remote bằng refspec :nhánh"
rule "${G}push[^;&|]*([[:space:]:]|refs/heads/)${MAIN}${E}" "push thẳng lên nhánh chính"
rule "${G}reset[^;&|]*${S}--hard" "git reset --hard làm mất thay đổi chưa commit"
rule "${G}clean[^;&|]*${S}(-[a-z]*f[a-z]*|--force)${E}" "git clean -f xoá file chưa track"
rule "${B}rm${S}+[^;&|]*(-[a-z]*r[a-z]*|--recursive)[^;&|]*${S}${RMT}${E}" "rm -r trên thư mục rộng"
# PowerShell/cmd: Remove-Item và alias (cả qua `cmd /c`), cờ -r(ecurse) hoặc /s, đích là ổ đĩa,
# gốc ổ hiện tại, thư mục nhà, . .. * (kể cả \* và *.*), trong nháy đơn hoặc kép.
# Dấu \ là dấu phân cách đường dẫn ở đây nên không coi là hết từ (.\dist không phải .).
PSE='([[:space:];&|)"'"'"']|$)'
Q='["'"'"']?'
W='(\*(\.\*)?)?'
PST="${Q}"'([a-z]:[\\/]?'"$W"'|[\\/]'"$W"'|~[\\/]?\*?|\$home[\\/]?\*?|\$\{?env:(userprofile|home|homedrive|systemdrive)\}?[\\/]?\*?|%(userprofile|homepath|homedrive|systemdrive)%[\\/]?\*?|\.\.?[\\/]?\*?|\*(\.\*)?)'"${Q}"
PSF='(-r[a-z]*(:\$true)?|/s)'
PSC="(${B}|cmd(\.exe)?(${S}+/[a-z])*${S}+/[ck]${S}+)(rm|ri|del|erase|rd|rmdir|remove-item)${S}+([^;&|]*${S})?"
rule "${PSC}(${PSF}${S}+([^;&|]*${S})?${PST}|${PST}${S}+([^;&|]*${S})?${PSF})${PSE}" "xoá đệ quy thư mục rộng (PowerShell/cmd)"
rule "(psql|mysql|mariadb|sqlite3|sqlcmd|duckdb|clickhouse)[^|&]*(drop${S}+(table|database|schema)|truncate${S})" "lệnh SQL xoá dữ liệu"
rule "${B}dropdb${S}|prisma${S}+migrate${S}+reset|db:(drop|reset)${E}" "xoá hoặc reset database"
rule "(npm|pnpm|yarn|bun|cargo)${O}${S}+publish" "publish package"
rule "twine${S}+upload|docker${O}${S}+push" "đẩy artifact lên registry"
rule "terraform${O}${S}+(apply|destroy)|kubectl${O}${S}+(apply|delete|replace|rollout|scale|drain)|helm${O}${S}+(install|upgrade|uninstall|delete|rollback)" "thay đổi hạ tầng"
rule "(vercel|netlify)[^;&|]*--prod|fly(ctl)?${O}${S}+deploy|${B}((npm|pnpm|yarn|bun)${S}+(run${S}+)?deploy|make${S}+deploy)${E}" "deploy"
rule "gh${O}${S}+pr${S}+merge|gh${O}${S}+release${S}+create" "merge PR hoặc tạo release (quyết định của người)"

# resolve_dir <gốc> <đường dẫn>: đường dẫn tuyệt đối giữ nguyên, tương đối thì nối vào gốc.
resolve_dir() {
  local d="$2"
  d="${d#\"}"; d="${d%\"}"; d="${d#\'}"; d="${d%\'}"
  case "$d" in
    \~ | \~/*) printf '%s\n' "$HOME${d#\~}" ;;
    /* | [A-Za-z]:*) printf '%s\n' "$d" ;;
    *) printf '%s\n' "$1/$d" ;;
  esac
}
# Đối số: trong nháy, hoặc chuỗi không có khoảng trắng. ARG_BS cho \<ký tự> là escape (bash:
# main\ repo); ARG_PS coi \ là ký tự thường (PowerShell: C:\vnstock\; git push). Xét cả hai.
ARG_BS='("[^"]*"|'"'"'[^'"'"']*'"'"'|([^[:space:];&|\\]|\\.)+\\?|\\)'
ARG_PS='("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:];&|]+)'

# last_arg <đoạn khớp> <regex đối số>: đối số cuối của đoạn, bỏ tiền tố -Path:, --git-dir=, GIT_DIR=...
last_arg() {
  local t="" re="$2"
  [[ $1 =~ ($re)$ ]] && t="${BASH_REMATCH[1]}"
  shopt -s nocasematch
  [[ $t =~ ^(-(literal)?path:|--chdir=|--git-dir=|--work-tree=|git_dir=|git_work_tree=)(.+)$ ]] && t="${BASH_REMATCH[3]}"
  shopt -u nocasematch
  printf '%s\n' "$t"
}

# expand_dir <đích>: bỏ nháy, thay $HOME, $PWD, $CLAUDE_PROJECT_DIR, $env:USERPROFILE, %USERPROFILE%.
# Còn biến, lệnh lồng hay
# %VAR% thì không biết thư mục: trả mã 1.
expand_dir() {
  local d="$1"
  d="${d#\"}"; d="${d%\"}"; d="${d#\'}"; d="${d%\'}"
  [ "$tool" = PowerShell ] || d="${d//\\ / }"
  d="${d/#\$HOME/$HOME}"
  d="${d/#\$\{HOME\}/$HOME}"
  d="${d/#\$PWD/${cwd:-.}}"
  d="${d/#\$\{PWD\}/${cwd:-.}}"
  [ -n "${CLAUDE_PROJECT_DIR:-}" ] && d="${d/#\$CLAUDE_PROJECT_DIR/$CLAUDE_PROJECT_DIR}"
  [ -n "${CLAUDE_PROJECT_DIR:-}" ] && d="${d/#\$\{CLAUDE_PROJECT_DIR\}/$CLAUDE_PROJECT_DIR}"
  d="${d/#%USERPROFILE%/${USERPROFILE:-$HOME}}"
  shopt -s nocasematch
  [[ $d =~ ^\$\{?env:(userprofile|home)\}?(.*)$ ]] && d="${USERPROFILE:-$HOME}${BASH_REMATCH[2]}"
  shopt -u nocasematch
  case "$d" in *'$'* | *'`'* | *%*%*) return 1 ;; esac
  printf '%s\n' "$d"
}

# Push khi có dính tới nhánh chính thì hỏi. Không đoán refspec hay lệnh nào chạy ở đâu (redirect,
# option, đường dẫn chứa chữ git/push, nhiều lệnh push, popd... đều làm việc đoán sai), mà gom
# MỌI thư mục lệnh có thể chạm tới: thư mục của phiên, đích của mọi cd/pushd/Set-Location (nối
# tiếp nhau), đích của mọi -C, --git-dir, --work-tree, GIT_DIR= (tính từ từng thư mục trên).
# Có một thư mục ở nhánh chính là hỏi; đích là biến hay lệnh lồng (không biết trước) cũng hỏi.
if [ -z "$reason" ] && printf '%s' "$cmd" | grep -Eiq -- "${G}push"; then
  base="${cwd:-.}"
  # cd của bash (kể cả trong bash -c '...', { }, if/then, có --, -P, -L), Set-Location/
  # Push-Location của PowerShell (kể cả -Path x, -Path:x, -PassThru).
  CDS='(cd|chdir|pushd|sl|set-location|push-location)'
  CDA='(^|[;&|(`"'"'"'{]|\$\(|(^|[[:space:]])(then|do|else|if|builtin|command|exec)[[:space:]])[[:space:]]*'
  dirs="$base$nl"
  unknown=""
  for a in "$ARG_BS" "$ARG_PS"; do
    CDRE="${CDS}((${S}+(--|-p|-l|-passthru))*)(${S}+-(literal)?path(:|${S}+)|${S}+)${a}"
    # Thư mục git chạy trong đó mà không cần cd.
    GDRE="(^|[[:space:];&|(])(-C${S}+|--chdir(=|${S}+)|--git-dir(=|${S}+)|--work-tree(=|${S}+)|GIT_DIR=|GIT_WORK_TREE=)${a}"
    for f in "${forms[@]}"; do
      cur="$base"
      cds="$base$nl"
      while IFS= read -r m; do
        [ -n "$m" ] || continue
        t="$(expand_dir "$(last_arg "$m" "$a")")" || { unknown=1; continue; }
        cur="$(resolve_dir "$cur" "$t")"
        cds="$cds$cur$nl"
      done <<EOF
$(printf '%s' "$f" | grep -Eio -- "${CDA}${CDRE}")
EOF
      dirs="$dirs$cds"
      while IFS= read -r m; do
        [ -n "$m" ] || continue
        t="$(expand_dir "$(last_arg "$m" "$a")")" || { unknown=1; continue; }
        while IFS= read -r c; do
          [ -n "$c" ] && dirs="$dirs$(resolve_dir "$c" "$t")$nl"
        done <<EOF
$cds
EOF
      done <<EOF
$(printf '%s' "$f" | grep -Eo -- "$GDRE")
EOF
    done
  done
  dirs="$(printf '%s' "$dirs" | awk '!s[$0]++')"
  [ -n "$unknown" ] && reason="push vào thư mục chưa biết trước (biến hoặc lệnh lồng)"
  while IFS= read -r d; do
    [ -n "$d" ] || continue # git -C "" là thư mục của chính hook, không phải của lệnh
    branch="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    if printf '%s' "$branch" | grep -Eqx -- "$MAIN"; then
      reason="push khi đang ở nhánh $branch"
      break
    fi
  done <<EOF
$dirs
EOF
fi

if [ -n "$reason" ]; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Hành động không đảo ngược được (%s). Cần người xác nhận, xem mục Quyền tự chủ trong CLAUDE.md."}}\n' "$reason"
fi
exit 0
