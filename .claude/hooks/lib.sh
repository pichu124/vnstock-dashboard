#!/usr/bin/env bash
# Hàm dùng chung cho các hook. File này được source, không chạy trực tiếp.
# Công cụ đọc JSON: jq, rồi Python, rồi sed. KIT_JSON_TOOL=jq|python|sed ép một cách (dùng trong test).

have_jq() {
  case "${KIT_JSON_TOOL:-auto}" in auto | jq) command -v jq >/dev/null 2>&1 ;; *) return 1 ;; esac
}

# hook_python: in tên Python thật đầu tiên chạy được. Bỏ qua bản giả "python3" của
# Microsoft Store trên Windows (có trong PATH nhưng không chạy được).
hook_python() {
  local c
  case "${KIT_JSON_TOOL:-auto}" in auto | python) ;; *) return 1 ;; esac
  for c in python3 python py; do
    if "$c" -c 'import json' >/dev/null 2>&1; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

# json_get <json> <khoá.lồng.nhau>: in giá trị chuỗi, số hoặc bool; in rỗng nếu không có.
json_get() {
  # Bỏ \r: jq/Python trên Windows có thể in xuống dòng kiểu CRLF, làm đường dẫn sai.
  _json_get_raw "$@" | tr -d '\r'
}

_json_get_raw() {
  local json="$1" path="$2" py
  if have_jq; then
    printf '%s' "$json" | jq -r --arg p "$path" 'getpath($p | split(".")) // empty | tostring' 2>/dev/null
    return 0
  fi
  if py="$(hook_python)"; then
    # Đọc và in bằng bytes UTF-8: trên Windows stdin mặc định là cp1252, chữ "Đ" làm decode hỏng.
    printf '%s' "$json" | "$py" -c '
import json, sys
try:
    d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
except Exception:
    sys.exit(0)
for k in sys.argv[1].split("."):
    d = d.get(k) if isinstance(d, dict) else None
if d is not None:
    s = str(d).lower() if isinstance(d, bool) else str(d)
    sys.stdout.buffer.write(s.encode("utf-8") + b"\n")
' "$path" 2>/dev/null
    return 0
  fi
  # sed: đọc chuỗi JSON kể cả ký tự escape (\" \\ \/), hoặc giá trị không phải chuỗi.
  local key="${path##*.}" flat out
  flat="$(printf '%s' "$json" | tr '\n' ' ')"
  local re_str='"'"$key"'"[[:space:]]*:[[:space:]]*"((\\.|[^"\\])*)"'
  local re_raw='"'"$key"'"[[:space:]]*:[[:space:]]*([^",}[:space:]]+)'
  out="$(printf '%s' "$flat" | sed -nE "s/.*${re_str}.*/\\1/p" | head -n 1)"
  if [ -n "$out" ]; then
    # Giải escape từ trái sang phải: \\ giữ chỗ trước, để \\n không bị đọc thành xuống dòng.
    local bs='\' ph=$'\001'
    out="${out//"$bs$bs"/$ph}"
    out="${out//"${bs}n"/$'\n'}"
    out="${out//"${bs}t"/$'\t'}"
    out="${out//"${bs}r"/}"
    out="${out//"$bs\""/\"}"
    out="${out//"$bs/"//}"
    out="${out//"$ph"/$bs}"
    printf '%s\n' "$out"
    return 0
  fi
  printf '%s' "$flat" | sed -nE "s/.*${re_raw}.*/\\1/p" | head -n 1
}

# find_up <thư mục bắt đầu> <đường dẫn tương đối>: tìm ngược lên tới gốc dự án.
find_up() {
  local d="$1" stop="${CLAUDE_PROJECT_DIR:-/}"
  while [ -n "$d" ]; do
    if [ -e "$d/$2" ]; then
      printf '%s\n' "$d/$2"
      return 0
    fi
    if [ "$d" = "/" ] || [ "$d" = "$stop" ]; then
      return 1
    fi
    d="$(dirname "$d")"
  done
  return 1
}
