#!/usr/bin/env bash
# Kiểm tra bộ agent team còn hợp lệ. Chỉ kiểm file CỦA KIT (agents, skills, hooks, scripts của kit),
# không đụng tới skill hay tài liệu riêng của dự án đã cài kit.
#   ./scripts/validate-kit.sh [file.md ...]   kiểm thêm link nội bộ trong các file markdown được nêu
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

KIT_AGENTS="architect implementer verifier reviewer gardener"
KIT_SKILLS="team-lead create-verify-skill correct agent-audit"
KIT_HOOKS="lib.sh guard-irreversible.sh stop-gate.sh post-edit-format.sh"
KIT_SCRIPTS="check.sh validate-kit.sh test-hooks.sh install-kit.sh test-install.sh audit-agent.sh test-audit.sh test-plugin.sh"

errors=0
err() {
  printf '✘ %s\n' "$*" >&2
  errors=$((errors + 1))
}

has_frontmatter() {
  [ "$(head -n 1 "$1")" = "---" ] && awk 'NR > 1 && $0 == "---" { found = 1; exit } END { exit !found }' "$1"
}

fm_value() {
  awk 'NR == 1 { next } $0 == "---" { exit } { print }' "$1" \
    | sed -n "s/^$2:[[:space:]]*//p" | head -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

in_list() {
  local value="$1" item
  shift
  for item in "$@"; do
    [ "$value" = "$item" ] && return 0
  done
  return 1
}

md_files=()
for name in $KIT_AGENTS; do
  f=".claude/agents/$name.md"
  if [ ! -f "$f" ]; then
    err "$f: thiếu agent của kit"
    continue
  fi
  md_files+=("$f")
  if ! has_frontmatter "$f"; then
    err "$f: thiếu frontmatter (--- ... ---)"
    continue
  fi
  [ "$(fm_value "$f" name)" = "$name" ] || err "$f: name phải là '$name'"
  [ -n "$(fm_value "$f" description)" ] || err "$f: thiếu 'description'"
  model="$(fm_value "$f" model)"
  if [ -n "$model" ] && ! in_list "$model" sonnet opus haiku fable inherit && [ "${model#claude-}" = "$model" ]; then
    err "$f: model '$model' không hợp lệ (sonnet|opus|haiku|fable|inherit|claude-...)"
  fi
  effort="$(fm_value "$f" effort)"
  if [ -n "$effort" ] && ! in_list "$effort" low medium high xhigh max; then
    err "$f: effort '$effort' không hợp lệ (low|medium|high|xhigh|max)"
  fi
  memory="$(fm_value "$f" memory)"
  if [ -n "$memory" ] && ! in_list "$memory" user project local; then
    err "$f: memory '$memory' không hợp lệ (user|project|local)"
  fi
done

for name in $KIT_SKILLS; do
  d=".claude/skills/$name"
  f="$d/SKILL.md"
  if [ ! -f "$f" ]; then
    err "$f: thiếu skill của kit"
    continue
  fi
  while IFS= read -r m; do md_files+=("$m"); done < <(find "$d" -type f -name '*.md' | sort)
  if ! has_frontmatter "$f"; then
    err "$f: thiếu frontmatter"
    continue
  fi
  [ "$(fm_value "$f" name)" = "$name" ] || err "$f: name phải là '$name'"
  desc="$(fm_value "$f" description)"
  [ -n "$desc" ] || err "$f: thiếu 'description'"
  [ "${#desc}" -le 1536 ] || err "$f: description dài hơn 1536 ký tự"
  # Menu / của Claude Code hiện < > thành &lt; &gt; (đã thấy trên Windows 2.1.296).
  case "$desc$(fm_value "$f" argument-hint)" in *'<'* | *'>'*) err "$f: description/argument-hint có dấu < hoặc >, menu sẽ hiện &lt; &gt;" ;; esac
  lines="$(wc -l < "$f")"
  [ "$lines" -le 500 ] || err "$f: $lines dòng (nên dưới 500, tách phần tham khảo ra file riêng)"
done

for extra in "$@"; do
  if [ -f "$extra" ]; then md_files+=("$extra"); else err "không có file: $extra"; fi
done

link_count=0
for md in "${md_files[@]}"; do
  base="$(dirname "$md")"
  while IFS= read -r target; do
    target="${target%%#*}"
    target="${target%% *}"
    case "$target" in '' | http://* | https://* | mailto:*) continue ;; esac
    link_count=$((link_count + 1))
    [ -e "$base/$target" ] || err "$md: link gãy → $target"
  done < <(grep -o '\]([^)]*)' "$md" | sed -e 's/^](//' -e 's/)$//')
done

settings=.claude/settings.json
hook_count=0
if [ -f "$settings" ]; then
  py=""
  for c in python3 python py; do
    if "$c" -c 'import json' >/dev/null 2>&1; then
      py="$c"
      break
    fi
  done
  if [ -n "$py" ]; then
    "$py" -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8-sig"))' "$settings" 2>/dev/null \
      || err "$settings: JSON không hợp lệ"
  elif command -v jq >/dev/null 2>&1; then
    jq empty "$settings" 2>/dev/null || err "$settings: JSON không hợp lệ"
  elif command -v node >/dev/null 2>&1; then
    node -e 'JSON.parse(require("fs").readFileSync(process.argv[1], "utf8").replace(/^﻿/, ""))' "$settings" 2>/dev/null \
      || err "$settings: JSON không hợp lệ"
  else
    printf '⚠ không có jq/python/node để kiểm tra JSON của %s\n' "$settings"
  fi
  # Chỉ kiểm hook của kit; hook riêng của dự án (python ..., ~/.claude/...) không thuộc phạm vi.
  for h in guard-irreversible.sh stop-gate.sh post-edit-format.sh; do
    hook=".claude/hooks/$h"
    hook_count=$((hook_count + 1))
    grep -q "\.claude/hooks/$h" "$settings" || err "$settings: chưa đăng ký hook của kit $h"
    [ -f "$hook" ] || { err "$hook: không tồn tại"; continue; }
    [ -x "$hook" ] || err "$hook: chưa có quyền chạy (chmod +x)"
  done
  # Windows: Claude Code chạy lệnh qua PowerShell tool là chính, matcher chỉ có Bash thì guard không bao giờ chạy.
  if [ -n "$py" ]; then
    "$py" - "$settings" <<'PYEOF' || err "$settings: matcher của guard-irreversible.sh phải khớp cả Bash và PowerShell (\"Bash|PowerShell\")"
import json, re, sys
d = json.load(open(sys.argv[1], encoding="utf-8-sig"))
need = {"Bash", "PowerShell"}
covered = set()
for g in d.get("hooks", {}).get("PreToolUse", []):
    if any("guard-irreversible.sh" in (h.get("command") or "") for h in g.get("hooks", [])):
        m = g.get("matcher") or "*"
        for t in need:
            try:
                if m == "*" or re.fullmatch(m, t):
                    covered.add(t)
            except re.error:
                pass
sys.exit(0 if covered == need else 1)
PYEOF
  else
    grep -Eq '"matcher": *"[^"]*PowerShell' "$settings" \
      || err "$settings: matcher của guard-irreversible.sh phải khớp cả Bash và PowerShell (\"Bash|PowerShell\")"
  fi
else
  err "$settings: không tồn tại (hook của kit chưa được đăng ký)"
fi

shell_files=()
for h in $KIT_HOOKS; do
  [ -f ".claude/hooks/$h" ] && shell_files+=(".claude/hooks/$h")
done
for s in $KIT_SCRIPTS; do
  [ -f "scripts/$s" ] && shell_files+=("scripts/$s")
done
[ -f plugin/run-hook.sh ] && shell_files+=(plugin/run-hook.sh)
for sh in "${shell_files[@]}"; do
  bash -n "$sh" 2>/dev/null || err "$sh: lỗi cú pháp bash"
done
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x -S warning "${shell_files[@]}" || err "shellcheck báo lỗi"
fi
if [ -f scripts/audit-agent.py ] && [ -n "${py:-}" ]; then
  "$py" -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read())' scripts/audit-agent.py 2>/dev/null \
    || err "scripts/audit-agent.py: lỗi cú pháp Python"
fi
# Bản plugin (repo kit): manifest phải khớp agent, hook và settings.json, không thì người cài plugin thiếu đồ.
if [ -f .claude-plugin/plugin.json ] && [ -f plugin/run-hook.sh ]; then
  if [ -n "${py:-}" ]; then
    "$py" - <<'PYEOF' || err ".claude-plugin: manifest của plugin lệch với file của kit (xem lỗi ở trên)"
import glob, json, re, sys
errs = []
plugin = json.load(open(".claude-plugin/plugin.json", encoding="utf-8"))
market = json.load(open(".claude-plugin/marketplace.json", encoding="utf-8"))
hooks = json.load(open(plugin["hooks"], encoding="utf-8"))["hooks"]
settings = json.load(open(".claude/settings.json", encoding="utf-8"))["hooks"]
agents = sorted("./" + f for f in glob.glob(".claude/agents/*.md"))
if sorted(plugin.get("agents", [])) != agents:
    errs.append(f"plugin.json agents phải liệt kê đủ {agents}")
if [p["name"] for p in market["plugins"]] != [plugin["name"]]:
    errs.append("marketplace.json phải có đúng một plugin trùng tên với plugin.json")
if "version" in plugin or any("version" in p for p in market["plugins"]):
    errs.append("không ghim version: plugin cập nhật theo commit (ghim thì commit mới không tới máy người dùng)")
if set(hooks) != set(settings):
    errs.append(f"hooks.json phải có cùng sự kiện với settings.json: {sorted(hooks)} vs {sorted(settings)}")
for event, groups in hooks.items():
    if len(groups) != len(settings.get(event, [])):
        errs.append(f"{event}: hooks.json có {len(groups)} nhóm hook, settings.json có {len(settings.get(event, []))}")
    for g, sg in zip(groups, settings.get(event, [])):
        if len(g["hooks"]) != len(sg["hooks"]):
            errs.append(f"{event}: nhóm matcher {g.get('matcher')!r} có {len(g['hooks'])} hook, settings.json có {len(sg['hooks'])}")
        if g.get("matcher") != sg.get("matcher"):
            errs.append(f"{event}: matcher {g.get('matcher')!r} khác settings.json {sg.get('matcher')!r}")
        for h, sh in zip(g["hooks"], sg["hooks"]):
            m = re.fullmatch(r'bash "\$\{CLAUDE_PLUGIN_ROOT\}/plugin/run-hook\.sh" ([\w-]+)', h["command"])
            if not m:
                errs.append(f"{event}: lệnh hook phải dạng bash \"${{CLAUDE_PLUGIN_ROOT}}/plugin/run-hook.sh\" <tên>: {h['command']}")
            elif not sh["command"].endswith(f".claude/hooks/{m.group(1)}.sh"):
                errs.append(f"{event}: plugin gọi {m.group(1)} còn settings.json gọi {sh['command']}")
            if h.get("timeout") != sh.get("timeout"):
                errs.append(f"{event}: timeout {h.get('timeout')} khác settings.json {sh.get('timeout')}")
for e in errs:
    print("  " + e, file=sys.stderr)
sys.exit(1 if errs else 0)
PYEOF
  else
    printf '⚠ không có Python để kiểm manifest của plugin\n'
  fi
fi
if [ -f scripts/test-hooks.sh ] && [ ! -f scripts/guard-ask-floor ]; then
  err "scripts/guard-ask-floor: không tồn tại (sàn số ca 'phải hỏi' của guard)"
fi

if [ "$errors" -gt 0 ]; then
  printf '✘ kit: %s lỗi\n' "$errors" >&2
  exit 1
fi
printf '✔ kit hợp lệ: %s agents, %s skills, %s hooks, %s link nội bộ\n' \
  "$(echo "$KIT_AGENTS" | wc -w | tr -d " ")" "$(echo "$KIT_SKILLS" | wc -w | tr -d " ")" "$hook_count" "$link_count"
