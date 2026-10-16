#!/usr/bin/env bash
# "The check": MỘT lệnh duy nhất mà agent, Stop hook và CI cùng chạy.
#   1. Luôn chạy scripts/validate-kit.sh. Test hành vi của hook (scripts/test-hooks.sh, khá chậm
#      trên Windows) chỉ chạy khi file của kit thay đổi, khi CI=true, hoặc KIT_SELFTEST=1.
#   2. Có scripts/check.local.sh thì chạy nó: đây là định nghĩa check thật của dự án.
#   3. Không có thì dùng `make check` nếu Makefile có target `check`.
#   4. Không có nữa thì tự nhận diện Node / Python / Go / Rust và chạy các check tìm thấy.
# Exit khác 0 nếu có bất kỳ check nào đỏ.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

failed=()
project_checks=0

step() {
  local name="$1"
  shift
  printf '\n▶ %s: %s\n' "$name" "$*"
  if "$@"; then
    printf '✔ %s\n' "$name"
  else
    printf '✘ %s (exit %s)\n' "$name" "$?"
    failed+=("$name")
  fi
}

project_step() {
  project_checks=$((project_checks + 1))
  step "$@"
}

missing() {
  printf '\n✘ %s\n' "$1"
  failed+=("$1")
}

tool() {
  if [ -x ".venv/bin/$1" ]; then
    printf '%s\n' ".venv/bin/$1"
  else
    command -v "$1"
  fi
}

node_checks() {
  local pm=npm
  if [ -f pnpm-lock.yaml ]; then pm=pnpm
  elif [ -f yarn.lock ]; then pm=yarn
  elif [ -f bun.lockb ] || [ -f bun.lock ]; then pm=bun
  fi
  if ! command -v "$pm" >/dev/null 2>&1; then
    missing "node: thiếu $pm"
    return
  fi
  if [ ! -d node_modules ]; then
    missing "node: chưa cài dependency (chạy '$pm install' trước)"
    return
  fi
  local s
  for s in lint typecheck type-check test; do
    if node -e 'process.exit(((require("./package.json").scripts) || {})[process.argv[1]] ? 0 : 1)' "$s" 2>/dev/null; then
      if [ "$s" = test ]; then
        project_step "node:$s" env CI=1 "$pm" run "$s"
      else
        project_step "node:$s" "$pm" run "$s"
      fi
    fi
  done
}

python_checks() {
  local t
  if t="$(tool ruff)"; then project_step "python:ruff" "$t" check .; fi
  if t="$(tool mypy)" && { [ -f mypy.ini ] || grep -qs '^\[tool\.mypy\]' pyproject.toml; }; then
    project_step "python:mypy" "$t" .
  fi
  if t="$(tool pytest)" && { [ -d tests ] || [ -d test ] || compgen -G "test_*.py" >/dev/null; }; then
    project_step "python:pytest" "$t" -q
  fi
}

go_checks() {
  if ! command -v go >/dev/null 2>&1; then
    missing "go: thiếu go"
    return
  fi
  project_step "go:vet" go vet ./...
  project_step "go:test" go test ./...
}

rust_checks() {
  if ! command -v cargo >/dev/null 2>&1; then
    missing "rust: thiếu cargo"
    return
  fi
  if cargo clippy --version >/dev/null 2>&1; then
    project_step "rust:clippy" cargo clippy --all-targets --quiet -- -D warnings
  fi
  project_step "rust:test" cargo test --quiet
}

if [ -x scripts/validate-kit.sh ]; then
  step "kit" ./scripts/validate-kit.sh
fi
kit_changed() {
  git status --porcelain -- .claude/hooks scripts/check.sh scripts/test-hooks.sh scripts/validate-kit.sh \
    scripts/guard-ask-floor scripts/audit-agent.sh scripts/audit-agent.py scripts/test-audit.sh \
    scripts/test-plugin.sh plugin/run-hook.sh plugin/hooks.json .claude-plugin 2>/dev/null | grep -q .
}
if [ -x scripts/test-hooks.sh ]; then
  if [ -n "${CI:-}" ] || [ "${KIT_SELFTEST:-0}" = 1 ] || kit_changed; then
    step "hooks" ./scripts/test-hooks.sh
    [ -x scripts/test-audit.sh ] && step "audit" ./scripts/test-audit.sh
    [ -x scripts/test-plugin.sh ] && step "plugin" ./scripts/test-plugin.sh
  else
    printf '\n• hooks: bỏ qua test của kit vì hook không đổi (KIT_SELFTEST=1 để chạy)\n'
  fi
fi

if [ -f scripts/check.local.sh ]; then
  project_step "project" bash scripts/check.local.sh
elif [ -f Makefile ] && grep -Eq '^check:' Makefile; then
  project_step "make check" make check
else
  [ -f package.json ] && node_checks
  { [ -f pyproject.toml ] || [ -f setup.cfg ] || [ -f requirements.txt ]; } && python_checks
  [ -f go.mod ] && go_checks
  [ -f Cargo.toml ] && rust_checks
fi

if [ "$project_checks" -eq 0 ] && [ "${#failed[@]}" -eq 0 ]; then
  printf '\n⚠ Chưa nhận diện được check nào của dự án. Hãy tạo scripts/check.local.sh (lint + typecheck + test nhanh).\n'
fi

if [ "${#failed[@]}" -gt 0 ]; then
  printf '\n✘ check.sh ĐỎ: %s\n' "${failed[*]}"
  exit 1
fi
printf '\n✔ check.sh XANH\n'
