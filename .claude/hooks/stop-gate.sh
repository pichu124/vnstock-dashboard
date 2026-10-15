#!/usr/bin/env bash
# Stop hook: agent chưa được kết thúc lượt khi ./scripts/check.sh còn đỏ.
# Chỉ chạy khi có thay đổi (chưa commit, hoặc commit chưa push) ở file không phải tài liệu.
#   AGENT_STOP_GATE=off       tắt gate cho phiên này
#   AGENT_STOP_GATE_MAX=<n>   số lần chặn liên tiếp tối đa trước khi nhả cho người xem (mặc định 3)
set -uo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

[ "${AGENT_STOP_GATE:-on}" = "off" ] && exit 0
input="$(cat)"

dir="$(json_get "$input" cwd)"
if [ -n "$dir" ]; then
  # Có cwd mà không phải thư mục: dừng, không đoán sang thư mục khác (có thể chạy nhầm check của repo khác).
  [ -d "$dir" ] || exit 0
else
  dir="${CLAUDE_PROJECT_DIR:-$PWD}"
fi
cd "$dir" 2>/dev/null || exit 0
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0
[ -x scripts/check.sh ] || exit 0

# Chống đệ quy: repo đang được stop gate chạy check thì không chạy lồng thêm lần nữa
# (check.sh chạy test của hook, test lại gọi stop gate).
case "|${AGENT_STOP_GATE_ACTIVE:-}|" in *"|$root|"*) exit 0 ;; esac
export AGENT_STOP_GATE_ACTIVE="${AGENT_STOP_GATE_ACTIVE:+$AGENT_STOP_GATE_ACTIVE|}$root"

session="$(json_get "$input" session_id)"
state_dir="${TMPDIR:-/tmp}/agent-stop-gate"
mkdir -p "$state_dir" 2>/dev/null
state="$state_dir/${session:-unknown}.count"

# Thay đổi = chưa commit + commit chưa có trên remote (có upstream thì so với upstream,
# không có thì lấy commit chưa nằm trên remote nào). quotePath=false để tên file có dấu
# không bị in thành "\303\272..." rồi lọt qua bộ lọc đuôi .md.
changed="$(
  {
    git -c core.quotePath=false diff --name-only
    git -c core.quotePath=false diff --cached --name-only
    git -c core.quotePath=false ls-files --others --exclude-standard
    if git rev-parse --verify -q '@{upstream}' >/dev/null; then
      git -c core.quotePath=false diff --name-only '@{upstream}...HEAD'
    elif [ -n "$(git remote)" ]; then
      git -c core.quotePath=false log --name-only --format= HEAD --not --remotes
    fi
  } 2>/dev/null | grep -v '^$' | grep -Ev '\.(md|mdx|txt|rst)$' | sort -u
)"
if [ -z "$changed" ]; then
  rm -f "$state"
  exit 0
fi

out="$(./scripts/check.sh 2>&1)"
status=$?
if [ "$status" -eq 0 ]; then
  rm -f "$state"
  exit 0
fi

count=$(( $(cat "$state" 2>/dev/null || echo 0) + 1 ))
max="${AGENT_STOP_GATE_MAX:-3}"
if [ "$count" -gt "$max" ]; then
  rm -f "$state"
  printf '{"systemMessage":"Stop gate: ./scripts/check.sh vẫn đỏ sau %s lần chặn liên tiếp. Agent được dừng để bạn xem xét."}\n' "$max"
  exit 0
fi
echo "$count" > "$state"

reason="$(
  echo "./scripts/check.sh đang đỏ (exit $status), chưa được kết thúc lượt (lần chặn $count/$max)."
  echo "Sửa nguyên nhân gốc rồi chạy lại ./scripts/check.sh. Không tắt check, không skip test, không nuốt lỗi."
  echo "Nếu lỗi nằm ngoài phạm vi task (đã đỏ sẵn trên nhánh gốc, thiếu môi trường) hoặc mâu thuẫn với yêu cầu của người dùng, nói rõ điều đó trong câu trả lời cuối."
  echo "--- 40 dòng cuối của output ---"
  printf '%s\n' "$out" | tail -n 40
)"

# Ưu tiên JSON {"decision":"block"} (hiển thị gọn hơn); không có jq/Python thì dùng exit 2 + stderr.
if have_jq; then
  jq -cn --arg r "$reason" '{decision: "block", reason: $r}'
  exit 0
elif py="$(hook_python)"; then
  "$py" -c 'import json, sys; print(json.dumps({"decision": "block", "reason": sys.argv[1]}))' "$reason"
  exit 0
fi
printf '%s\n' "$reason" >&2
exit 2
