#!/usr/bin/env bash
# PostToolUse(Edit|Write): format file vừa sửa, chỉ bằng formatter mà dự án ĐÃ cấu hình.
# Không bao giờ chặn agent: lỗi format sẽ do ./scripts/check.sh bắt.
set -uo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

input="$(cat)"
file="$(json_get "$input" tool_input.file_path)"
[ -n "$file" ] && [ -f "$file" ] || exit 0
dir="$(dirname "$file")"

has_prettier_config() {
  local f
  for f in .prettierrc .prettierrc.json .prettierrc.yaml .prettierrc.yml .prettierrc.js .prettierrc.cjs \
           .prettierrc.mjs prettier.config.js prettier.config.cjs prettier.config.mjs; do
    find_up "$dir" "$f" >/dev/null && return 0
  done
  local pkg
  pkg="$(find_up "$dir" package.json)" && grep -q '"prettier"[[:space:]]*:' "$pkg"
}

case "$file" in
  *.js|*.jsx|*.ts|*.tsx|*.mjs|*.cjs|*.mts|*.cts|*.json|*.jsonc|*.css|*.scss|*.html|*.vue|*.svelte|*.yaml|*.yml)
    if bin="$(find_up "$dir" node_modules/.bin/biome)" && { find_up "$dir" biome.json >/dev/null || find_up "$dir" biome.jsonc >/dev/null; }; then
      "$bin" format --write "$file" >/dev/null 2>&1
    elif bin="$(find_up "$dir" node_modules/.bin/prettier)" && has_prettier_config; then
      "$bin" --write "$file" >/dev/null 2>&1
    fi
    ;;
  *.py)
    if py="$(find_up "$dir" pyproject.toml)" && grep -q '^\[tool\.ruff' "$py" || find_up "$dir" ruff.toml >/dev/null || find_up "$dir" .ruff.toml >/dev/null; then
      ruff="$(find_up "$dir" .venv/bin/ruff || command -v ruff)" && "$ruff" format "$file" >/dev/null 2>&1
    elif py="$(find_up "$dir" pyproject.toml)" && grep -q '^\[tool\.black\]' "$py"; then
      black="$(find_up "$dir" .venv/bin/black || command -v black)" && "$black" -q "$file" >/dev/null 2>&1
    fi
    ;;
  *.go)
    command -v gofmt >/dev/null 2>&1 && gofmt -w "$file" >/dev/null 2>&1
    ;;
esac
exit 0
