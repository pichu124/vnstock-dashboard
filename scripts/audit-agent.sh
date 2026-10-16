#!/usr/bin/env bash
# Dò sự cố của đội agent từ file phiên Claude Code. Chỉ đọc. Xem scripts/audit-agent.py.
#   scripts/audit-agent.sh [--since 7] [--all] [--out bao-cao.md] [--json] [--no-replay]
# Soát dự án ở thư mục hiện tại; --all soát mọi dự án trên máy (kit cài dạng plugin).
set -uo pipefail
here="$(dirname "$0")"
# shellcheck source=SCRIPTDIR/../.claude/hooks/lib.sh
. "$here/../.claude/hooks/lib.sh"

py="$(KIT_JSON_TOOL=python hook_python)" || {
  echo "Cần Python 3 (python3, python hoặc py) để đọc file phiên." >&2
  exit 1
}
# Python trên Windows không chạy được đường dẫn kiểu /usr/bin/bash hay /c/...: đổi sang dạng Windows nếu có cygpath.
AUDIT_BASH="$BASH"
script="$here/audit-agent.py"
if command -v cygpath >/dev/null 2>&1; then
  AUDIT_BASH="$(cygpath -w "$BASH")"
  script="$(cygpath -w "$script")"
fi
export AUDIT_BASH PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
exec "$py" "$script" "$@"
