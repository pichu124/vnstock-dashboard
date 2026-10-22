#!/usr/bin/env bash
# Hàm dùng chung cho các hook. File này được source, không chạy trực tiếp.
# Công cụ đọc JSON: jq, rồi Python, rồi awk. KIT_JSON_TOOL=jq|python|sed ép một cách (dùng trong test; sed là
# tên cũ của cách không dùng jq/Python, nay đọc bằng awk).

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
  # Không có jq/Python (KIT_JSON_TOOL=sed): một lần awk, thời gian tuyến tính theo độ dài JSON. Không dùng
  # ${x//a/b} trên chuỗi lớn: bash 3.2 (macOS) mất 13 giây với lệnh 15 KB, quá timeout của hook.
  # Lấy lần xuất hiện cuối của khoá: chuỗi (giải escape \" \\ \/ \n \t, bỏ \r), hoặc giá trị không phải chuỗi.
  printf '%s' "$json" | LC_ALL=C awk -v k="\"${path##*.}\"" '
    { s = s $0 " " }
    END {
      hs = 0
      while ((i = index(s, k)) > 0) {
        s = substr(s, i + length(k))
        if (match(s, /^[ \t\r]*:[ \t\r]*"([^"\\]|\\.)*"/)) {
          str = substr(s, 1, RLENGTH - 1)
          sub(/^[ \t\r]*:[ \t\r]*"/, "", str)
          hs = 1
        } else if (match(s, /^[ \t\r]*:[ \t\r]*[^", \t\r}]+/)) {
          raw = substr(s, 1, RLENGTH)
          sub(/^[ \t\r]*:[ \t\r]*/, "", raw)
        }
      }
      if (!hs) {
        if (raw != "") print raw
        exit
      }
      # Giải escape từ trái sang phải: \\ giữ chỗ trước, để \\n không bị đọc thành xuống dòng.
      gsub(/\\\\/, "\001", str)
      gsub(/\\n/, "\n", str)
      gsub(/\\t/, "\t", str)
      gsub(/\\r/, "", str)
      gsub(/\\"/, "\"", str)
      gsub(/\\\//, "/", str)
      # Tách bằng regex: awk của macOS tách theo ký tự đơn thì tách cả ở xuống dòng. In dần, không nối chuỗi.
      n = split(str, part, /\001/)
      printf "%s", part[1]
      for (j = 2; j <= n; j++) printf "\\%s", part[j]
      printf "\n"
    }'
}

# text_grep <chuỗi> <tham số grep...>: grep trên chuỗi, trả đúng mã của grep.
# Không viết thẳng `printf | grep -q` dưới pipefail: grep -q thoát ở dòng khớp đầu tiên, printf còn
# ghi dở thì chết vì SIGPIPE (141), cả pipeline thành 141 và "khớp" bị đọc thành "không khớp".
# Không dùng <<<: chuỗi lớn (và mọi chuỗi trên bash < 5.1) đi qua file tạm, đĩa đầy hay TMPDIR
# không ghi được thì grep không chạy.
text_grep() {
  local s="$1"
  shift
  printf '%s' "$s" 2>/dev/null | grep "$@"
  return "${PIPESTATUS[1]}"
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
