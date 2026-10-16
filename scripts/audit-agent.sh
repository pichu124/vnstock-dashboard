#!/usr/bin/env bash
# Dò sự cố của đội agent từ file phiên Claude Code. Chỉ đọc. Xem scripts/audit-agent.py.
#   ./scripts/audit-agent.sh [--since 7] [--out bao-cao.md] [--json] [--no-replay]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=SCRIPTDIR/../.claude/hooks/lib.sh
. .claude/hooks/lib.sh

py="$(KIT_JSON_TOOL=python hook_python)" || {
  echo "Cần Python 3 (python3, python hoặc py) để đọc file phiên." >&2
  exit 1
}
# Python trên Windows không chạy được đường dẫn kiểu /usr/bin/bash: đổi sang dạng Windows nếu có cygpath.
AUDIT_BASH="$BASH"
command -v cygpath >/dev/null 2>&1 && AUDIT_BASH="$(cygpath -w "$BASH")"
export AUDIT_BASH PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
exec "$py" scripts/audit-agent.py "$@"
