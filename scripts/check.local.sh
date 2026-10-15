#!/usr/bin/env bash
# Check thật của vnstock-dashboard cho đội agent.
# Mặc định chạy đúng danh sách `--fast` trong run.py (cmd_test), nhưng gọi pytest trực tiếp
# để KHÔNG ghi data_warehouse/_meta/test_status.json (badge dùng chung giữa hai máy).
#   CHECK_FULL=1  chạy toàn bộ tests/ (như trước khi mở PR)
#   PYTHON=...    chỉ định interpreter
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

py="${PYTHON:-}"
if [ -z "$py" ]; then
  for c in .venv/Scripts/python.exe .venv/bin/python python3 python py; do
    if "$c" -c 'import pytest' >/dev/null 2>&1; then
      py="$c"
      break
    fi
  done
fi
if [ -z "$py" ]; then
  echo "Không tìm thấy Python có pytest. Kích hoạt venv hoặc đặt PYTHON=..." >&2
  exit 1
fi

if [ "${CHECK_FULL:-0}" = 1 ]; then
  exec "$py" -m pytest tests/ -q -p no:cacheprovider
fi

fast="$("$py" - <<'PYEOF'
import ast, pathlib
tree = ast.parse(pathlib.Path("run.py").read_text(encoding="utf-8"))
for fn in ast.walk(tree):
    if isinstance(fn, ast.FunctionDef) and fn.name == "cmd_test":
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)
                    and any(getattr(t, "id", None) == "test_paths" for t in node.targets)
                    and len(node.value.elts) > 1):
                print("\n".join(e.value for e in node.value.elts if isinstance(e, ast.Constant)))
                raise SystemExit
PYEOF
)"
if [ -z "$fast" ]; then
  echo "Không đọc được danh sách --fast trong run.py (cmd_test.test_paths). Sửa script này cho khớp run.py." >&2
  exit 1
fi
# shellcheck disable=SC2086
exec "$py" -m pytest $fast -q -p no:cacheprovider
