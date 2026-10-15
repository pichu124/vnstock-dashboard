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
# Nối dòng bị ngắt bằng \ (bash) hoặc ` (PowerShell): grep so từng dòng, nên lệnh và đích
# nằm khác dòng sẽ bị bỏ sót, còn dấu \ cuối dòng lại bị coi là đường dẫn gốc ổ.
nl=$'\n'
cmd="${cmd//"\\$nl"/ }"
cmd="${cmd//"\`$nl"/ }"

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
O='([[:space:]]+-[^[:space:]]+([[:space:]]+("[^"]*"|'"'"'[^'"'"']*'"'"'|[^-[:space:]"'"'"'][^[:space:]]*))?)*'
# Vị trí bắt đầu một lệnh (để `git rm` không bị coi là `rm`).
B='(^|[;&|(`"'"'"'{]|\$\(|(^|[[:space:]])(then|do|else|time|xargs|exec|nohup|env)[[:space:]])[[:space:]]*(sudo[[:space:]]+)?'
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
ARG='("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:];&|]+)'

# Đang đứng trên nhánh chính thì MỌI `git push` đều hỏi: không đoán refspec, vì redirect
# (2>&1), option (-o ci.skip) hay đường dẫn có dấu cách đều làm việc đoán sai.
if [ -z "$reason" ] && printf '%s' "$cmd" | grep -Eiq -- "${G}push"; then
  base="${cwd:-.}"
  dir="$base"
  before="${cmd%git*push*}"
  # cd của bash, Set-Location/Push-Location (kể cả -Path/-LiteralPath) của PowerShell.
  CDS='(cd|chdir|pushd|sl|set-location|push-location)'
  last_cd="$(printf '%s' "$before" | grep -Eio -- "(^|[;&|(])[[:space:]]*${CDS}(${S}+-(literal)?path)?${S}+${ARG}" | tail -n 1 \
    | sed -E 's/^[;&|(]?[[:space:]]*[A-Za-z-]+([[:space:]]+-[A-Za-z]*[Pp][Aa][Tt][Hh])?[[:space:]]+//')"
  [ -n "$last_cd" ] && dir="$(resolve_dir "$dir" "$last_cd")"
  c_dir="$(printf '%s' "$cmd" | grep -Eo -- "git([[:space:]]+-[^[:space:]]+)*[[:space:]]+-C${S}+${ARG}" | head -n 1 \
    | sed -E 's/.*-C[[:space:]]+//')"
  [ -n "$c_dir" ] && dir="$(resolve_dir "$dir" "$c_dir")"
  # popd/Pop-Location có thể đưa về thư mục cũ, đường dẫn có thể không resolve được ($env:X):
  # khi đó xét thêm thư mục của phiên. Thà hỏi thừa.
  dirs="$dir"
  if ! git -C "$dir" rev-parse --git-dir >/dev/null 2>&1 \
    || printf '%s' "$before" | grep -Eiq -- '(^|[;&|(])[[:space:]]*(popd|pop-location)'; then
    dirs="$dir
$base"
  fi
  while IFS= read -r d; do
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
