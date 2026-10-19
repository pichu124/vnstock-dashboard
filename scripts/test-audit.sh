#!/usr/bin/env bash
# Test của scripts/audit-agent.py bằng file phiên Claude Code giả (cùng định dạng JSONL thật).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
root="$PWD"
# shellcheck source=SCRIPTDIR/../.claude/hooks/lib.sh
. .claude/hooks/lib.sh
py="$(KIT_JSON_TOOL=python hook_python)" || {
  printf '⚠ bỏ qua test audit: cần Python 3\n'
  exit 0
}
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# Không để lại scripts/__pycache__: file chưa track sẽ làm Stop gate tưởng có thay đổi.
export PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1

# Repo đang ở nhánh main: guard hỏi mọi git push chạy ở đây.
git init -q -b main "$tmp/mainrepo" && git -C "$tmp/mainrepo" -c user.email=t@t -c user.name=t -c commit.gpgsign=false commit -q --allow-empty -m i
# Tạo file phiên giả: phiên chính + một subagent implementer + một file cũ (ngoài --since).
"$py" - "$tmp/t" "$tmp/mainrepo" <<'PYEOF'
import json, os, sys, time
d = sys.argv[1]
# cwd giả: kết quả không được phụ thuộc chỗ đặt repo kit (vd verifier chạy check trong worktree tạm của nó).
cwd = "/khong-co-tren-may/kitproj"
os.makedirs(d + "/s1/subagents", exist_ok=True)
lines = []
NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def call(i, cmd, tool="Bash", result="ok", pd=None, guard=None, out=lines, ts=None, text="done", where=None):
    out.append({"type": "assistant", "cwd": where or cwd, "timestamp": ts or NOW,
                "message": {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": tool, "input": {"command": cmd}}]}})
    if guard is not None:
        out.append({"type": "attachment", "attachment": {"type": "hook_success", "hookName": "PreToolUse:" + tool, "toolUseID": i,
                    "hookEvent": "PreToolUse", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-irreversible.sh", "exitCode": 0,
                    "stdout": guard}})
    if result == "rejected":
        out.append({"type": "user", "toolUseResult": "User rejected tool use", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": i, "is_error": True,
             "content": "The user doesn't want to proceed with this tool use. The tool use was rejected."}]}})
    elif result == "denied":
        out.append({"type": "user", "permissionDecision": pd or {"decision": "reject", "source": "config"}, "message": {"role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": i, "is_error": True, "content": "Permission to use Bash has been denied."}]}})
    else:
        out.append({"type": "user", "permissionDecision": pd or {"decision": "accept", "source": "config", "reasonType": "classifier"},
                    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": text}]}})
ASK = '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Hành động không đảo ngược được (x)."}}'
call("t1", "git checkout -- .")
call("t2", "git push --force origin feat/x", result="rejected", guard=ASK)
call("t3", "rm -rf node_modules && rm -rf /tmp/build")
call("t4", "git push origin main", pd={"decision": "accept", "source": "user_temporary"}, guard=ASK)
call("t5", "echo hello", guard=ASK)
call("t6", "Remove-Item -Recurse -Force src", tool="PowerShell")
call("t7", "cat > notes.txt <<'EOF'\ngit checkout -- .\ngit stash drop\nEOF\nls")
call("t8", "ls -la", result="rejected")
call("t9", "git commit -m \"push to main\" && git push -u origin feat/x")
call("t10", "git push -u origin feat/x && git checkout main")
# Các ca reviewer tìm ra ở bản đầu.
call("h1", "git reset --hard HEAD~3")                                   # chạy khi guard chưa nạp; nay guard hỏi
call("h2", "git push --force origin x", result="denied", guard=ASK)       # bị cấu hình chặn: D, không phải C
call("h3", "cat transcript.txt", text="... The user doesn't want to proceed ... (chỉ là output)")
call("h4", 'Set-Location "C:\\vnstock\\"; Remove-Item -Recurse -Force data_warehouse\\prices; Write-Host "ok"', tool="PowerShell")
call("h5", "rm -rf ~/build-important")
call("h6", "D=/tmp/x; rm -rf $D; D=$HOME/src; rm -rf $D")
call("h7", "cd build && rm -rf ../src")
call("h8", "bash <<'X'\nrm -rf src\nX")
call("h9", 'cmd /c "rd /s /q src"')
call("h10", "git branch -D ancient", ts="2020-01-01T00:00:00Z")          # phiên mới nhưng dòng cũ: ngoài --since
call("h11", "rm -rf $SP/rv6")                                           # đích là biến không biết: vẫn báo
call("h12", "SP=/tmp/claude-0/scratchpad; cd $SP/rv7 && rm -rf repos new")
# Ca biên của reviewer lần hai.
call("k1", "git clean --force -d")
call("k2", 'echo "git stash drop" | sh')
call("k3", "cat <<'EOF' | bash\ngit stash drop\nEOF")
call("k4", "cat > notes.txt <<'EOF'; git stash drop\nghi chú\nEOF")
call("k5", "rm -rf build/../src")
call("k6", "cd /tmp/x && cd && rm -rf proj")
call("k7", "rm -rf node_modules /c")
call("m1", "git push", where=sys.argv[2])
# Claude Code trên Windows (2.1.296) không ghi kết quả guard vào file phiên: suy từ hộp hỏi.
call("n1", "git push --force origin y", result="rejected")                # bạn từ chối ở hộp hỏi -> D
call("n2", "git push -u origin main", pd={"decision": "accept", "source": "user_temporary"})
# Báo cáo desktop 16/10: branch -d (chữ thường, xoá an toàn) bị báo nhầm; G không ghi ai chặn.
call("b1", "git branch -d wt-u1 wt-u2")
call("b2", "git branch -D wip-chua-gop")
call("g2", "cat data/bao-cao.csv", result="denied", pd={"decision": "reject", "source": "config", "reasonType": "classifier"})  # bạn duyệt -> C, không phải H                                 # push lúc đang ở main, không khớp mẫu chữ
# Báo cáo desktop 18/10: subagent dọn worktree tạm của chính nó (.claude/worktrees/agent-<hex>, nhánh worktree-agent-<hex>).
WT = cwd + "/.claude/worktrees/agent-abc"
call("w1", "git -C .claude/worktrees/agent-a1b2c3d4e5f60718 status --short && git branch -D worktree-agent-a1b2c3d4e5f60718")
call("w2", "git branch -D worktree-agent-aeb4c21e13a20ddd0 2>&1; rm -rf .claude/worktrees/agent-aeb4c21e13a20ddd0 && git worktree prune")
call("w3", 'for b in fix/ur-runner fix/us-stale fix/ual-alerts; do git merge-base --is-ancestor "refs/heads/$b" origin/trial/agent-team && git branch -D "$b"; done')
call("w4", 'echo "# drift" >> skill/agent-audit/mode.md ; cat skill/agent-audit/mode.md ; git checkout -- skill/agent-audit/mode.md')
call("w5", "rm -rf src", where=WT)  # chỉ vô hại nhờ cwd của phiên: nay vẫn nghi (xem assert)
call("w6", "cd .claude/worktrees/agent-abc && rm -rf src")
call("w7", 'Remove-Item -Recurse -Force "C:\\Users\\Ten Nguoi\\repo\\.claude\\worktrees\\agent-abc"', tool="PowerShell")
# Vẫn nghi: nhánh thường, worktree phiên của app (có thể chứa việc của bạn), thoát khỏi worktree, merge-base trước khi xoá.
call("x1", "git branch -D feature-x")
call("x2", "git branch -D worktree-agent-abc feature-x")
call("x3", "rm -rf .claude/worktrees")
call("x4", "rm -rf .claude/worktrees/quirky-mayer-c977af")
call("x5", "rm -rf .claude/worktrees/agent-abc/../..")
call("x6", "git merge-base --is-ancestor a main; git branch -D a")
call("x7", "git merge-base --is-ancestor a main && git branch -D b")
call("x8", "git merge-base --is-ancestor a main || git branch -D a")
call("x9", "! git merge-base --is-ancestor a main && git branch -D a")
call("x10", "cd && rm -rf proj", where=WT)
call("x11", "cd .. && rm -rf src", where=WT)
call("x12", "cd $D && rm -rf src", where=WT)
# Reviewer 18/10: cwd của phiên không phải một cd tường minh. Lấy nó làm thư mục xuất phát thì mọi đích "tương đối"
# (biến chưa biết, lệnh lồng, cd có cờ hay sau if/do/builtin, xargs) đều thành vô hại. Các ca này phải vẫn nghi.
call("y1", "rm -rf $PROJECT_ROOT/src", where=WT)
call("y2", 'rm -rf "$REPO/src"', where=WT)
call("y3", 'rm -rf "$(git rev-parse --git-common-dir)"', where=WT)
call("y4", "cd -- /home/u/proj && rm -rf src", where=WT)
call("y5", "cd -P /home/u/proj && rm -rf src", where=WT)
call("y6", "if cd /home/u/proj; then rm -rf src; fi", where=WT)
call("y7", "for d in /home/u/proj; do cd $d; rm -rf src; done", where=WT)
call("y8", "builtin cd /home/u/proj && rm -rf src", where=WT)
call("y9", "ls /home/u/proj | xargs rm -rf", where=WT)
call("y10", "rm -rf $SP/rv6", where=WT)
# Cùng các ca đó sau một cd vào worktree agent: không suy thư mục theo cd, nên vẫn nghi.
IN = "cd .claude/worktrees/agent-abc && "
call("z1", IN + "rm -rf $PROJECT_ROOT/src")
call("z2", IN + 'rm -rf "$(git rev-parse --git-common-dir)"')
call("z3", IN + "rm -rf `git rev-parse --show-toplevel`")
call("z4", IN + "rm -rf +(.)/src")                     # extglob: +(.) khớp ..
call("z5", IN + "rm -rf {.,.}./src")                   # brace: thành ../src ../src
call("z6", IN + "cd -- /home/u/proj && rm -rf src")
call("z7", IN + "cd -P /home/u/proj && rm -rf src")
call("z8", "cd .claude/worktrees/agent-abc; if cd /home/u/proj; then rm -rf src; fi")
call("z9", "cd .claude/worktrees/agent-abc; for d in /home/u/proj; do cd $d; rm -rf src; done")
call("z10", IN + "builtin cd /home/u/proj && rm -rf src")
call("z11", IN + "ls /home/u/proj | xargs rm -rf")
call("z12", "rm -rf .claude/worktrees/agent-abc/$REL")   # $REL có thể là ../..
call("z13", "rm -rf .claude/worktrees/agent-abc/`cat<p`")
call("z14", "rm -rf .claude/worktrees/agent-abc/{.,.}./quirky-mayer-c977af")
# merge-base trước khi xoá không làm việc xoá nhánh thành vô hại (lead bỏ quy tắc này 18/10).
call("v1", "git merge-base --is-ancestor a main && git -C ../khac branch -D a")
call("v2", "git -C ../khac merge-base --is-ancestor a main && git branch -D a")
call("v3", "git --git-dir=../khac/.git merge-base --is-ancestor a main && git branch -D a")
call("v4", "git merge-base --is-ancestor a main && git --work-tree=../khac branch -D a")
call("v5", "git merge-base --is-ancestor a a && git branch -D a")
# Lead chốt 18/10 (sau review vòng 2): bỏ suy thư mục theo cd. Chỉ vô hại khi đích ghi TRỌN là worktree agent
# (.claude/worktrees/agent-<hex>, không biến, glob, brace, dấu phẩy, khoảng trắng, `..`, `.`), và xoá nhánh
# khi cả đoạn lệnh chỉ là `git branch -D worktree-agent-<hex>...` (bỏ redirect ở đuôi). Các ca review vòng 2: vẫn nghi.
call("r1", "(cd .claude/worktrees/agent-abc && npm run build) && rm -rf out")
call("r2", "(cd .claude/worktrees/agent-abc/ ); rm -rf src")
call("r3", "cd .claude/worktrees/agent-abc && bash -c 'cd ../../..; rm -rf src'")
call("r4", "cd .claude/worktrees/agent-abc && eval cd /; rm -rf home")
call("r5", "cd .claude/worktrees/agent-abc && FOO=1 cd / && rm -rf home")
call("r6", "cd .claude/worktrees/agent-abc && time cd / && rm -rf home")
call("r7", "cd .claude/worktrees/agent-abc/ & rm -rf src")
call("r8", "Remove-Item -Recurse -Force C:\\repo\\src,C:\\repo\\.claude\\worktrees\\agent-abc", tool="PowerShell")
call("r9", "Remove-Item -Recurse -Force -LiteralPath C:\\repo\\src,C:\\repo\\.claude\\worktrees\\agent-abc", tool="PowerShell")
call("r10", "Remove-Item -Recurse -Force C:\\repo\\.claude\\worktrees\\agent-abc,C:\\repo\\src", tool="PowerShell")
call("r11", "echo main | xargs git branch -D worktree-agent-abc")
call("r12", "git branch -D worktree-agent-abc main")
call("r13", "git branch -D worktree-agent-abc >main")                   # ghi đè file main: không phải redirect bỏ được
call("r14", "rm -rf .claude/worktrees/agent-abc/..")
call("r15", "rm -rf .claude/worktrees/agent-abc/.")
call("r16", "rm -rf .claude/worktrees/agent-abc*")
call("r17", "rm -rf .claude/worktrees/agent-xyz")
call("r18", "rm -rf .claude/worktrees/agent-abc ~/x")
call("r19", "cd /tmp/x && ls / | xargs rm -rf")                        # đích đọc từ stdin, dù đang ở thư mục tạm
call("r20", "xargs .claude/worktrees/agent-abc/rm -rf .claude/worktrees/agent-abc")
# Review vòng 3: với bash, `\` là ký tự thoát chứ không phải dấu phân cách. `\` cuối đích nối đích với phần sau nó (dòng kế,
# `; x`, `| x`), `\` sau agent-<hex> dán tên kế tiếp vào thành thư mục khác nằm cạnh. Biến (gán tạm `D=x lệnh` không đổi
# biến của shell), IFS, `-Tên:giá-trị` của PowerShell: đích thật khác đích ghi. Các ca này vẫn nghi.
call("e1", "rm -rf .claude/worktrees/agent-abc\\\n  src")                 # bash xoá cả ./src
call("e2", "rm -rf .claude/worktrees/agent-abc\\; /home")
call("e3", "rm -rf .claude/worktrees/agent-abc\\| /home")
call("e4", "rm -rf .claude/worktrees/agent-abc/sub\\\n /home/u/proj")
call("e5", "rm -rf .claude/worktrees/agent-abc\\-old")                     # bash xoá .claude/worktrees/agent-abc-old
call("e6", "X=.claude/worktrees/agent-abc/home; IFS=c; rm -rf $X")         # tách thành . laude/worktrees/agent-ab /home
call("e7", "IFS=c; rm -rf .claude/worktrees/agent-abc/home")               # báo thừa có chủ ý: canh kiểm IFS độc lập với kiểm $
call("e8", "Remove-Item -Path:C:\\proj\\* -Recurse -Force -Exclude C:\\proj\\.claude\\worktrees\\agent-abc", tool="PowerShell")
call("e9", "D=/; D=.claude/worktrees/agent-abc true; rm -rf $D")           # bash xoá /
# Vô hại: dòng thật trên desktop (18/10), đường tuyệt đối, ~, PowerShell, nhiều nhánh tạm, redirect ở đuôi.
call("d1", "cd /c/Users/admin/automarking && git branch -D worktree-agent-aeb4c21e13a20ddd0 2>&1; "
           "rm -rf .claude/worktrees/agent-aeb4c21e13a20ddd0 && git worktree prune")
call("d2", "rm -rf /c/Users/admin/automarking/.claude/worktrees/agent-abc123")
call("d3", "Remove-Item -Recurse -Force C:\\Users\\admin\\automarking\\.claude\\worktrees\\agent-abc123", tool="PowerShell")
call("d4", "git branch -D worktree-agent-abc worktree-agent-def")
call("d5", "rm -rf ~/automarking/.claude/worktrees/agent-abc123/ ./.claude/worktrees/agent-def/src")
call("d6", "git branch --delete --force worktree-agent-abc >/dev/null 2>&1")
# Nối dòng: bash bỏ `\` + xuống dòng trước khi tách lệnh. Tách tại \n trước thì đích ở dòng sau bị mất.
call("c1", "rm -rf dist\\\n  src")                                       # bash xoá dist src
call("c2", "rm -rf /tmp/x\\\n  src")                                     # bash xoá /tmp/x src
call("c3", "ls | xargs \\\n  rm -rf /tmp/x")                             # bash chạy ls | xargs rm -rf /tmp/x
call("c4", "echo a\\\\\nrm -rf src")                                     # `\\` là một `\` thường: xuống dòng là dấu ngắt thật
call("c5", "rm -rf /tmp/x\\\nsrc")                                       # không thụt lề: bash xoá MỘT đích /tmp/xsrc
# Sau `--` mọi token là đích, kể cả token mở bằng `-`. GNU rm hoán vị tham số: `--` sau đích vẫn kết thúc cờ.
call("s1", "rm -rf -- -important /tmp/x")                               # xoá cả ./-important
call("s2", "rm -rf /tmp/x -- -y")                                       # xoá cả ./-y
call("s3", "rm -rf -- /tmp/x")                                          # `--` không phải đích: chỉ xoá /tmp/x
call("s4", "(cd /tmp && true); rm -rf -- -x")                           # cd trong subshell không đổi thư mục: xoá ./-x của dự án
call("s5", "cd dist && cd .. && rm -rf -- -x")                          # về lại thư mục dự án: xoá ./-x
call("s6", "cd /tmp/w; rm -rf -- -x")                                   # cd lỗi thì `;` vẫn chạy rm: xoá ./-x của dự án
lines.append({"type": "assistant", "message": "chuỗi thay vì object"})
lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": ["list"]}}]}})
lines.append({"type": "system", "subtype": "stop_hook_summary", "hookInfos": ["chuỗi"], "hookErrors": [1]})
lines.append({"type": "attachment", "attachment": "chuỗi"})
BLOCK = "[\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-gate.sh]: ./scripts/check.sh đang đỏ (exit 1), chưa được kết thúc lượt (lần chặn 1/3).\n"
lines.append({"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n" + BLOCK}})
lines.append({"type": "system", "subtype": "stop_hook_summary", "timestamp": NOW,
              "hookInfos": [{"command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-gate.sh", "durationMs": 125000}],
              "hookErrors": [BLOCK]})
lines.append({"type": "attachment", "timestamp": NOW, "attachment": {"type": "hook_system_message", "hookName": "Stop", "hookEvent": "Stop",
              "content": "Stop gate: ./scripts/check.sh vẫn đỏ sau 3 lần chặn liên tiếp. Agent được dừng để bạn xem xét."}})
lines.append({"type": "attachment", "attachment": {"type": "hook_non_blocking_error", "hookName": "PreToolUse:Bash",
              "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-irreversible.sh", "exitCode": 127,
              "stderr": "Failed with non-blocking status code: guard-irreversible.sh: line 2: $'\\r': command not found"}})
with open(d + "/s1.jsonl", "w", encoding="utf-8") as f:
    for e in lines:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    f.write("{hỏng\n")
sub = []
call("u1", "git stash drop", out=sub)
with open(d + "/s1/subagents/agent-a1.jsonl", "w", encoding="utf-8") as f:
    for e in sub:
        f.write(json.dumps(e) + "\n")
with open(d + "/s1/subagents/agent-a1.meta.json", "w", encoding="utf-8") as f:
    json.dump({"agentType": "implementer"}, f)
old = []
call("o1", "git branch -D old-work", out=old)
with open(d + "/old.jsonl", "w", encoding="utf-8") as f:
    for e in old:
        f.write(json.dumps(e) + "\n")
past = time.time() - 30 * 86400
os.utime(d + "/old.jsonl", (past, past))
PYEOF

out="$tmp/report.json"
./scripts/audit-agent.sh --project "$root" --transcripts "$tmp/t" --since 7 --json > "$out"
code=$?
md="$(./scripts/audit-agent.sh --project "$root" --transcripts "$tmp/t" --since 7)"
./scripts/audit-agent.sh --project "$root" --transcripts "$tmp/khong-co" >/dev/null 2>&1
nofile=$?

# Cài dạng plugin: chạy script của kit từ thư mục dự án KHÁC (chưa cài kit), và --all quét mọi dự án.
plain="$tmp/plain proj"
git init -q -b feat/x "$plain" && git -C "$plain" -c user.email=t@t -c user.name=t -c commit.gpgsign=false commit -q --allow-empty -m i
mkdir -p "$plain/.claude"
printf '\\bdanger-cmd\\b\tlệnh riêng của dự án\n' > "$plain/.claude/audit-watch.txt"
"$py" - "$tmp/cfg/projects" "$plain" "$tmp/mainrepo" <<'PYEOF'
import json, os, sys, time
base, plain, main = sys.argv[1:4]
NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
PLUG = 'bash "C:/Users/Ten Nguoi/.claude/plugins/cache/agents-team-coding/agent-team/abc123/plugin/run-hook.sh" '
def write(name, cwd, calls, extra=()):
    os.makedirs(f"{base}/{name}", exist_ok=True)
    with open(f"{base}/{name}/s.jsonl", "w", encoding="utf-8") as f:
        for i, cmd in calls:
            f.write(json.dumps({"type": "assistant", "cwd": cwd, "timestamp": NOW, "message": {"role": "assistant",
                    "content": [{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": cmd}}]}}) + "\n")
            f.write(json.dumps({"type": "user", "permissionDecision": {"decision": "accept", "source": "config", "reasonType": "classifier"},
                    "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": "ok"}]}}) + "\n")
        for e in extra:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
write("-plain", plain, [("p1", "git push --force origin feat/x"), ("p2", "danger-cmd now")], extra=[
    {"type": "attachment", "attachment": {"type": "hook_non_blocking_error", "hookName": "PreToolUse:Bash",
     "command": PLUG + "guard-irreversible", "exitCode": 127, "stderr": "bash: line 1: python3: command not found"}},
    {"type": "system", "subtype": "stop_hook_summary", "timestamp": NOW,
     "hookInfos": [{"command": PLUG + "stop-gate", "durationMs": 12},
                   {"command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-gate.sh", "durationMs": 4000}], "hookErrors": []}])
write("-main", main, [("q1", "danger-cmd later"), ("q2", "git reset --hard HEAD~1")])
# Dự án tự cài kit + máy có plugin: mỗi lệnh có hai bản ghi guard (thứ tự không cố định). Một bản hỏi là đã hỏi.
ASK = '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Hành động không đảo ngược được (y)."}}'
def guard_rec(i, out, cmd):
    return {"type": "attachment", "attachment": {"type": "hook_success", "hookName": "PreToolUse:Bash", "toolUseID": i,
            "hookEvent": "PreToolUse", "command": cmd, "exitCode": 0, "stdout": out}}
write("-dual", plain, [("d1", "echo dual-1"), ("d2", "echo dual-2")], extra=[
    guard_rec("d1", ASK, PLUG + "guard-irreversible"), guard_rec("d1", "", "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-irreversible.sh"),
    guard_rec("d2", "", "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-irreversible.sh"), guard_rec("d2", ASK, PLUG + "guard-irreversible")])
PYEOF
other="$tmp/other.json"
(cd "$plain" && CLAUDE_CONFIG_DIR="$tmp/cfg" "$root/scripts/audit-agent.sh" --transcripts "$tmp/cfg/projects/-plain" --json > "$other")
all="$tmp/all.json"
(cd "$tmp" && CLAUDE_CONFIG_DIR="$tmp/cfg" "$root/scripts/audit-agent.sh" --all --since 1 --json > "$all")
allmd="$(cd "$tmp" && CLAUDE_CONFIG_DIR="$tmp/cfg" "$root/scripts/audit-agent.sh" --all --since 1)"

# Mục I (bạn phải sửa agent) và J (chỉ số tuần): thư mục phiên riêng, để các assert đếm file ở trên không đổi.
learnrepo="$tmp/learnrepo"
git init -q -b feat/x "$learnrepo" && mkdir -p "$learnrepo/sub"
"$py" - "$tmp/learn" "$learnrepo" "$tmp/learn-expect.json" <<'PYEOF'
import json, os, sys, time
from datetime import datetime
d, repo, expect = sys.argv[1:4]
sub = os.path.join(repo, "sub")
T2 = int(time.time())
T1 = T2 - 8 * 86400  # luôn rơi vào tuần ISO khác T2
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
week = lambda t: "%d-W%02d" % tuple(datetime.fromtimestamp(t).isocalendar()[:2])
HUMAN = {"kind": "human"}
def write(name, rows):
    os.makedirs(os.path.dirname(f"{d}/{name}"), exist_ok=True)
    with open(f"{d}/{name}", "w", encoding="utf-8") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
def user(t, cwd, content, **kw):
    return dict({"type": "user", "timestamp": iso(t), "cwd": cwd, "message": {"role": "user", "content": content}}, **kw)
def asst(t, cwd, *blocks):
    return {"type": "assistant", "timestamp": iso(t), "cwd": cwd, "message": {"role": "assistant", "content": list(blocks)}}
def tool(i, name, inp):
    return {"type": "tool_use", "id": i, "name": name, "input": inp}
def text(s):
    return {"type": "text", "text": s}
def result(t, cwd, i, txt, err=False):
    return user(t, cwd, [{"type": "tool_result", "tool_use_id": i, "content": txt, "is_error": err}])
REJ = "The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it was a file edit, the new_string was NOT written to the file)."
BLOCK = "[\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-gate.sh]: ./scripts/check.sh đang đỏ (exit 1), chưa được kết thúc lượt (lần chặn 1/3).\n"
def stop(t, cwd):
    return {"type": "system", "subtype": "stop_hook_summary", "timestamp": iso(t), "cwd": cwd,
            "hookInfos": [{"command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-gate.sh", "durationMs": 900}], "hookErrors": [BLOCK]}
# Tuần trước. Tên file xếp sau cùng: thứ tự trong mục I phải theo giờ, không theo file.
write("z-w1.jsonl", [
    user(T1, repo, "vẫn lỗi từ hôm qua, xem giúp", origin=HUMAN),  # đầu file, chưa có agent nào để sửa: không phải câu sửa
    asst(T1, repo, tool("e1", "Edit", {"file_path": "/x/a.py", "old_string": "a", "new_string": "b"})),
    result(T1, repo, "e1", REJ + " To tell you how to proceed, the user said:\n  đừng đụng file này,\nsửa test trước  ", err=True),
    asst(T1, repo, text("Đã dừng.")),
    user(T1, repo, [text("có đúng không?")]),  # dạng list, không có origin (bản cũ)
    user(T1, repo, "Nắp hộp vẫn bịt kín chứ?", origin=HUMAN),  # "vẫn bị" chỉ khớp trọn từ
    stop(T1, repo),
])
# Tuần này, cwd là thư mục con của repo.
write("w2.jsonl", [
    user(T2, sub, "Làm mục J", origin=HUMAN),
    asst(T2, sub, tool("b1", "Bash", {"command": "pytest -q"})),
    result(T2, sub, "b1", "ok"),
    asst(T2, sub, tool("b2", "Bash", {"command": "git push origin feat/x"})),
    result(T2, sub, "b2", REJ + " STOP what you are doing and wait for the user to tell you how to proceed.", err=True),  # không kèm lời
    user(T2, sub, [text("[Request interrupted by user for tool use]")]),  # dấu của lần từ chối trên: không phải ngắt
    user(T2, sub, [text("vẫn lỗi khi\nchạy   check")], origin=HUMAN),
    asst(T2, sub, text("Đang xem lại")),
    user(T2, sub, [text("[Request interrupted by user]")], uuid="w2-esc"),  # Esc lúc model đang viết: ngắt thật
    user(T2, sub, "Stop hook feedback:\nsai rồi", isMeta=True),
    user(T2, sub, "This session is being continued... sai rồi", isCompactSummary=True, isVisibleInTranscriptOnly=True),
    user(T2, sub, "Another Claude session sent a message: vẫn lỗi", origin={"kind": "peer", "name": "reviewer"}),
    user(T2, sub, "<command-message>team-lead</command-message>\n<command-name>/team-lead</command-name>\n"
                  "<command-args>bạn quên chạy test rồi</command-args>", origin=HUMAN),
    user(T2, sub, "<local-command-stdout>sai rồi</local-command-stdout>"),
    user(T2, sub, "sửa lỗi sai chính tả trong README", origin=HUMAN),
    stop(T2, "/khong-co-tren-may/otherproj"),
])
# Phiên Windows đọc trên máy khác: dự án là tên thư mục cuối của cwd.
WIN = "C:\\Users\\Ten Nguoi\\winproj"
write("win.jsonl", [
    user(T2, WIN, "Đọc file cấu hình giúp tôi", origin=HUMAN),
    asst(T2, WIN, tool("r1", "Read", {"file_path": WIN + "\\cfg.json"})),
    result(T2, WIN, "r1", "{}"),
    user(T2, WIN, "That's WRONG, I told you to use utf-8", origin=HUMAN),
])
def agent(name, typ, rows):
    write(f"w2/subagents/agent-{name}.jsonl", rows)
    with open(f"{d}/w2/subagents/agent-{name}.meta.json", "w", encoding="utf-8") as f:
        json.dump({"agentType": typ}, f)
agent("v1", "agent-team:verifier", [
    user(T2, sub, "Kiểm chứng mục J. Lần trước vẫn lỗi."),
    asst(T2, sub, text("Đang chạy check.")),
    user(T2, sub, "sai rồi, làm lại"),  # lead gửi subagent, không phải bạn gõ
    asst(T2, sub, text("Xong.\n\n**KẾT LUẬN: PASS**")),
])
agent("r1", "reviewer", [
    user(T2, sub, "Review diff"),
    asst(T2, sub, text("KẾT LUẬN: CHẶN\nđể xem lại")),
    asst(T2, sub, tool("h1", "SubagentHandback", {"message": "Đã xem lại.\n**KẾT LUẬN: KHÔNG CHẶN**"})),
])
agent("r2", "reviewer", [
    user(T2, sub, "Review diff 2"),
    asst(T2, sub, tool("h2", "SubagentHandback", {"message": "KẾT LUẬN: CHẶN (một lỗi, mức trung bình)"})),
])
agent("i1", "implementer", [
    user(T2, sub, "Làm việc X"),
    asst(T2, sub, text("Verifier sẽ ghi KẾT LUẬN: FAIL nếu đỏ.")),
])
with open(expect, "w", encoding="utf-8") as f:
    json.dump({"w1": week(T1), "w2": week(T2), "w2_local": datetime.fromtimestamp(T2).strftime("%Y-%m-%d %H:%M"), "sub": sub}, f)
PYEOF
learn="$tmp/learn.json"
./scripts/audit-agent.sh --transcripts "$tmp/learn" --since 30 --no-replay --json > "$learn"
learncode=$?
learnmd="$(./scripts/audit-agent.sh --all --transcripts "$tmp/learn" --since 30 --no-replay)"

# Ca reviewer tìm ra ở mục I/J. Mỗi ca một dự án riêng, để các dòng mục J không lẫn vào nhau.
wtmain="$tmp/mainproj"
git init -q -b main "$wtmain" && git -C "$wtmain" -c user.email=t@t -c user.name=t -c commit.gpgsign=false commit -q --allow-empty -m i
git -C "$wtmain" worktree add -q --detach "$tmp/wt-elsewhere" && mkdir -p "$tmp/wt-elsewhere/pkg"
git -C "$wtmain" worktree add -q --detach "$wtmain/.claude/worktrees/feat-c"
"$py" - "$tmp/review" "$wtmain" "$tmp/wt-elsewhere" <<'PYEOF'
import json, os, sys, time
d, wtmain, elsewhere = sys.argv[1:4]
T = int(time.time())
NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T))
HUMAN = {"kind": "human"}
def write(name, rows):
    os.makedirs(os.path.dirname(f"{d}/{name}"), exist_ok=True)
    with open(f"{d}/{name}", "w", encoding="utf-8") as f:
        for e in rows:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
def user(cwd, content, **kw):
    return dict({"type": "user", "timestamp": NOW, "cwd": cwd, "message": {"role": "user", "content": content}}, **kw)
def asst(cwd, *blocks, **kw):
    return dict({"type": "assistant", "timestamp": NOW, "cwd": cwd, "message": {"role": "assistant", "content": list(blocks)}}, **kw)
def text(s):
    return {"type": "text", "text": s}
# Tin gõ trong IDE: block ngữ cảnh máy chèn đứng trước lời bạn. Thẻ máy biết rõ thì bỏ cả tin; thẻ khác là bạn dán vào.
IDE = "/khong-co-tren-may/ideproj"
OPENED = "<ide_opened_file>The user opened the file /x/a.py in the IDE. This may or may not be related to the current task.</ide_opened_file>"
write("ide.jsonl", [
    user(IDE, "Sửa hàm parse", origin=HUMAN),
    asst(IDE, text("Đã sửa.")),
    user(IDE, [text(OPENED), text("sai rồi, đừng sửa file này")], origin=HUMAN),
    user(IDE, "<system-reminder>\nNhắc: vẫn lỗi\n</system-reminder>\n<ide_selection>The user selected the lines 3 to 5 from /x/a.py:\nwrong\n</ide_selection>\n"
              "bạn quên chạy test", origin=HUMAN),
    user(IDE, [text(OPENED), text("<bash-input>git status sai rồi</bash-input>")], origin=HUMAN),
    user(IDE, "<bash-stdout>sai rồi</bash-stdout><bash-stderr></bash-stderr>"),
    user(IDE, "<bash-stderr>wrong</bash-stderr>"),
    user(IDE, "<task-notification>\n<task-id>b1</task-id>\n<summary>vẫn lỗi</summary>\n</task-notification>"),
    user(IDE, "<local-command-caveat>Caveat: sai rồi</local-command-caveat>"),
    user(IDE, '<div class="err">Nút này vẫn sai màu</div> sửa giúp', origin=HUMAN),
])
# Một phiên có bản chép ở hai thư mục dự án (worker khởi động lại, resume): mỗi dòng chỉ được đếm một lần.
DUP = "/khong-co-tren-may/dupproj"
REJ = "The user doesn't want to proceed with this tool use. The tool use was rejected. To tell you how to proceed, the user said:\n  đừng push"
BLOCK = "[\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop-gate.sh]: ./scripts/check.sh đang đỏ (exit 1), chưa được kết thúc lượt (lần chặn {}/3).\n"
shared = [
    user(DUP, "Làm việc Y", origin=HUMAN, uuid="d-u1"),
    asst(DUP, {"type": "tool_use", "id": "dy1", "name": "Bash", "input": {"command": "git push origin feat/y"}}, uuid="d-a1"),
    user(DUP, [{"type": "tool_result", "tool_use_id": "dy1", "is_error": True, "content": REJ}], uuid="d-u2"),
    asst(DUP, text("Đã dừng."), uuid="d-a2"),
    user(DUP, "vẫn sai, làm lại", origin=HUMAN, uuid="d-u3"),
    user(DUP, [text("[Request interrupted by user]")], uuid="d-u4"),
    {"type": "system", "subtype": "stop_hook_summary", "timestamp": NOW, "cwd": DUP, "uuid": "d-s1",
     "hookInfos": [{"command": "stop-gate.sh", "durationMs": 10}], "hookErrors": [BLOCK.format(1), BLOCK.format(2)]},
    {"type": "attachment", "uuid": "d-r1", "timestamp": NOW, "cwd": DUP, "attachment": {"type": "hook_system_message", "hookName": "Stop",
     "hookEvent": "Stop", "content": "Stop gate: ./scripts/check.sh vẫn đỏ sau 3 lần chặn liên tiếp. Agent được dừng để bạn xem xét."}},
    {"type": "attachment", "uuid": "d-h1", "timestamp": NOW, "cwd": DUP, "attachment": {"type": "hook_non_blocking_error",
     "hookName": "PreToolUse:Bash", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-irreversible.sh", "exitCode": 1,
     "stderr": "Failed with non-blocking status code: guard-irreversible.sh: lỗi giả"}},
    user(DUP, "bạn nhầm rồi", origin=HUMAN),  # bản cũ không có uuid: khử trùng theo nội dung
]
write("-dup/s.jsonl", shared)
write("-dup-dupproj/s.jsonl", shared + [user(DUP, "ok tiếp", origin=HUMAN, uuid="d-u5")])
for proj in ("-dup", "-dup-dupproj"):
    write(f"{proj}/s/subagents/agent-v.jsonl", [user(DUP, "Kiểm chứng việc Y", uuid="d-v0"),
                                                asst(DUP, text("KẾT LUẬN: PASS"), uuid="d-v1")])
    with open(f"{d}/{proj}/s/subagents/agent-v.meta.json", "w", encoding="utf-8") as f:
        json.dump({"agentType": "verifier"}, f)
# Bản chép khi worker khởi động lại ghi cwd mới vào dòng cũ: I/J phải quy dòng đó về cùng cwd mà mục G dùng.
def copy_at(cwd):
    return [user(cwd, "Làm việc W", origin=HUMAN, uuid="w-u1"),
            asst(cwd, {"type": "tool_use", "id": "wr1", "name": "Bash", "input": {"command": "git push origin feat/w"}}, uuid="w-a1"),
            user(cwd, [{"type": "tool_result", "tool_use_id": "wr1", "is_error": True, "content": REJ + " w"}], uuid="w-u2")]
write("-wr/s.jsonl", copy_at("/khong-co-tren-may/wrcopy"))
write("-wr-wrorig/s.jsonl", copy_at("/khong-co-tren-may/wrorig"))
# Câu sửa: "bảo vệ/bảo mật" không phải "đã bảo", "vẫn chưa được merge" là hỏi trạng thái; người dùng hay gõ "ko".
RX = "/khong-co-tren-may/rxproj"
write("rx.jsonl", [
    user(RX, "Thêm guard cho push", origin=HUMAN),
    asst(RX, text("Đã thêm.")),
    user(RX, "guard đã bảo vệ nhánh main chưa?", origin=HUMAN),
    user(RX, "tôi đã bảo mật file .env chưa?", origin=HUMAN),
    user(RX, "PR này vẫn chưa được merge à?", origin=HUMAN),
    user(RX, "test vẫn chưa chạy xong à?", origin=HUMAN),
    user(RX, "ko đúng, vẫn chưa được", origin=HUMAN),
    user(RX, "đã bảo là chạy test trước", origin=HUMAN),
])
# Bấm "No" ở hộp xin phép: tool_result từ chối rồi NGAY SAU là dấu ngắt, chép từ file phiên thật (2.1.300, 15/10).
# Dấu đó thuộc về lần từ chối (đã đếm ở D/G), không phải một lần ngắt. Esc lúc model đang viết thì vẫn là ngắt.
REAL_REJ = ("The user doesn't want to proceed with this tool use. The tool use was rejected "
            "(eg. if it was a file edit, the new_string was NOT written to the file).")
def asked_no(cwd, n, cmd, tail):
    return [asst(cwd, {"type": "tool_use", "id": n + "-t", "name": "Bash", "input": {"command": cmd}}, uuid=n + "-a"),
            user(cwd, [{"type": "tool_result", "content": REAL_REJ + tail, "is_error": True, "tool_use_id": n + "-t"}],
                 uuid=n + "-r", parentUuid=n + "-a", toolUseResult="User rejected tool use", toolDenialKind="user-rejected",
                 sourceToolAssistantUUID=n + "-a"),
            user(cwd, [text("[Request interrupted by user for tool use]")], uuid=n + "-i", parentUuid=n + "-r")]
STOP = " STOP what you are doing and wait for the user to tell you how to proceed."
RJ, ESC, RJN = "/khong-co-tren-may/rjproj", "/khong-co-tren-may/escproj", "/khong-co-tren-may/rjnoteproj"
write("rj.jsonl", [user(RJ, "Đẩy nhánh trial lên", origin=HUMAN, uuid="rj-p")]
      + asked_no(RJ, "rj1", "git push --force origin trial/agent-team", STOP)
      + [user(RJ, "Thử guard", origin=HUMAN, uuid="rj-p2")]
      + asked_no(RJ, "rj2", "git push --force origin khong-co-nhanh-nay", STOP))
write("esc.jsonl", [
    user(ESC, "Viết README", origin=HUMAN, uuid="esc-p"),
    asst(ESC, {"type": "tool_use", "id": "esc-t", "name": "Bash", "input": {"command": "ls docs"}}, uuid="esc-a"),
    user(ESC, [{"type": "tool_result", "content": "a.md", "is_error": False, "tool_use_id": "esc-t"}], uuid="esc-r"),
    asst(ESC, text("Đang viết README"), uuid="esc-a2"),
    user(ESC, [text("[Request interrupted by user]")], uuid="esc-i"),
])
write("rjn.jsonl", [user(RJN, "Đẩy nhánh", origin=HUMAN, uuid="rjn-p")]
      + asked_no(RJN, "rjn1", "git push origin main", " To tell you how to proceed, the user said:\n  đẩy lên nhánh feat thôi"))
# Lần từ chối không có dấu ngắt đi kèm, rồi bạn gõ lượt hỏi mới và bấm Esc trước khi agent kịp trả lời:
# lượt hỏi đã khép lần từ chối, nên Esc đó là một lần ngắt thật.
RJP = "/khong-co-tren-may/rjpromptproj"
write("rjp.jsonl", [user(RJP, "Đẩy nhánh", origin=HUMAN, uuid="rjp-p")]
      + asked_no(RJP, "rjp1", "git push --force origin feat/z", STOP)[:2]
      + [user(RJP, "Thôi, viết README trước", origin=HUMAN, uuid="rjp-p2"),
         user(RJP, [text("[Request interrupted by user]")], uuid="rjp-i")])
# Bấm No ở Edit: D/G chỉ ghi lệnh shell, nên lần từ chối này không có ở đâu khác. Dấu ngắt đi sau vẫn đếm là ngắt.
EDP = "/khong-co-tren-may/editproj"
write("ed.jsonl", [
    user(EDP, "Sửa README", origin=HUMAN, uuid="ed-p"),
    asst(EDP, {"type": "tool_use", "id": "ed-t", "name": "Edit", "input": {"file_path": "README.md", "old_string": "a", "new_string": "b"}},
         uuid="ed-a"),
    user(EDP, [{"type": "tool_result", "content": REAL_REJ + STOP, "is_error": True, "tool_use_id": "ed-t"}], uuid="ed-r",
         parentUuid="ed-a", toolUseResult="User rejected tool use", toolDenialKind="user-rejected", sourceToolAssistantUUID="ed-a"),
    user(EDP, [text("[Request interrupted by user for tool use]")], uuid="ed-i", parentUuid="ed-r"),
])
# Lần từ chối không có dấu ngắt, agent trả lời, rồi bạn bấm Esc: câu trả lời đã khép lần từ chối, Esc là ngắt thật.
RJA = "/khong-co-tren-may/rjanswerproj"
write("rja.jsonl", [user(RJA, "Đẩy nhánh", origin=HUMAN, uuid="rja-p")]
      + asked_no(RJA, "rja1", "git push --force origin feat/q", STOP)[:2]
      + [asst(RJA, text("Đã dừng, chờ bạn."), uuid="rja-a2"),
         user(RJA, [text("[Request interrupted by user]")], uuid="rja-i")])
# Từ chối kèm dấu ngắt, task nền xong mở lượt mới (tin máy chèn không khép lần từ chối), rồi bạn bấm Esc trước khi
# agent kịp viết gì: chỉ dấu ngắt đầu thuộc về lần từ chối, dấu thứ hai là một lần ngắt thật.
RJT = "/khong-co-tren-may/rjtaskproj"
write("rjt.jsonl", [user(RJT, "Đẩy nhánh", origin=HUMAN, uuid="rjt-p")]
      + asked_no(RJT, "rjt1", "git push --force origin feat/t", STOP)
      + [user(RJT, "<task-notification>\n<task-id>b2</task-id>\n<summary>test xong</summary>\n</task-notification>", uuid="rjt-n"),
         user(RJT, [text("[Request interrupted by user]")], uuid="rjt-i2")])
# Bấm No mà chỉ toolUseResult cho biết là từ chối: (i) tool_result không có khoá is_error, (ii) is_error nhưng nội dung
# không mở bằng câu từ chối quen thuộc. Vẫn là lần từ chối: dấu ngắt đi kèm được nuốt, lệnh vào G với người từ chối.
# Dựng tay từ asked_no; chưa thấy dạng chỉ có toolUseResult trong file phiên thật.
TUR = "/khong-co-tren-may/turonlyproj"
tur1 = asked_no(TUR, "tur1", "git push --force origin feat/t1", STOP)
del tur1[1]["message"]["content"][0]["is_error"]
tur2 = asked_no(TUR, "tur2", "git push --force origin feat/t2", STOP)
tur2[1]["message"]["content"][0]["content"] = ("The user doesn't want to take this action right now. STOP what you are doing "
                                               "and wait for the user to tell you how to proceed.")
write("tur.jsonl", [user(TUR, "Đẩy nhánh t1", origin=HUMAN, uuid="tur-p")] + tur1
      + [user(TUR, "Đẩy nhánh t2", origin=HUMAN, uuid="tur-p2")] + tur2)
# Worktree quy về repo chính: theo đường dẫn .claude/worktrees (cả máy khác), hoặc theo file .git của worktree có trên máy.
write("wt.jsonl", [user(cwd, "Làm việc trong worktree", origin=HUMAN) for cwd in (
    "C:\\Users\\Ten Nguoi\\wtproj\\.claude\\worktrees\\feat-a", "/khong-co-tren-may/wtproj/.claude/worktrees/feat-b/src",
    os.path.join(elsewhere, "pkg"), os.path.join(wtmain, ".claude", "worktrees", "feat-c"))])
PYEOF
review="$tmp/review.json"
./scripts/audit-agent.sh --transcripts "$tmp/review" --since 30 --no-replay --json > "$review"

"$py" - "$out" "$code" "$nofile" "$md" "$other" "$all" "$plain" "$allmd" "$learn" "$learncode" "$learnmd" "$tmp/learn-expect.json" "$review" <<'PYEOF'
import importlib.util, json, os, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
code, nofile, md = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
fails = []
total = 0
def check(cond, msg):
    global total
    total += 1
    if not cond:
        fails.append(msg)
cmds = lambda k: {i["command"] for i in r[k]}
check(code == 0, f"audit phải exit 0, được {code}")
check(nofile == 2, f"không có file phiên thì exit 2, được {nofile}")
check(r["files"] == 2, f"--since phải bỏ file cũ: đọc {r['files']} file, cần 2")
check(r["bad_lines"] == 5, f"1 dòng JSON hỏng + 4 dòng sai hình dạng phải được đếm, được {r['bad_lines']}")
check("git checkout -- ." in cmds("A_possible_misses"), "A phải có git checkout -- .")
check("Remove-Item -Recurse -Force src" in cmds("A_possible_misses"), "A phải có Remove-Item -Recurse src (PowerShell)")
check("git stash drop" in cmds("A_possible_misses"), "A phải có lệnh của subagent")
check(any(i["who"] == "implementer" for i in r["A_possible_misses"]), "phải ghi agentType của subagent")
for harmless in ("rm -rf node_modules && rm -rf /tmp/build", "ls -la", "git commit -m \"push to main\" && git push -u origin feat/x",
                 "git push -u origin feat/x && git checkout main"):
    check(harmless not in cmds("A_possible_misses"), f"A không được có lệnh vô hại: {harmless}")
check("cat > notes.txt <<'EOF'\ngit checkout -- .\ngit stash drop\nEOF\nls" not in cmds("A_possible_misses"), "nội dung heredoc là dữ liệu, không phải lệnh")
check("git branch -D old-work" not in cmds("A_possible_misses"), "file ngoài --since không được đọc")
check(cmds("B_regressions") == {"echo hello"}, f"B phải là đúng ca guard từng hỏi mà nay cho qua: {cmds('B_regressions')}")
check(cmds("C_asked_approved") == {"git push origin main", "echo hello", "git push -u origin main"}, f"C chỉ gồm lệnh guard hỏi và được duyệt: {cmds('C_asked_approved')}")
check(cmds("D_asked_rejected") == {"git push --force origin feat/x", "git push --force origin x", "git push --force origin y"}, f"D sai: {cmds('D_asked_rejected')}")
check(cmds("H_ran_unguarded") == {"git reset --hard HEAD~3", "git clean --force -d", "git push"}, f"H (guard không hỏi lúc chạy, nay hỏi) sai: {cmds('H_ran_unguarded')}")
A = cmds("A_possible_misses")
for must in ('Set-Location "C:\\vnstock\\"; Remove-Item -Recurse -Force data_warehouse\\prices; Write-Host "ok"',
             "rm -rf ~/build-important", "D=/tmp/x; rm -rf $D; D=$HOME/src; rm -rf $D", "cd build && rm -rf ../src",
             "bash <<'X'\nrm -rf src\nX", 'cmd /c "rd /s /q src"', "rm -rf $SP/rv6"):
    check(must in A, f"A phải có: {must!r}")
for must in ('echo "git stash drop" | sh', "cat <<'EOF' | bash\ngit stash drop\nEOF",
             "cat > notes.txt <<'EOF'; git stash drop\nghi chú\nEOF", "rm -rf build/../src",
             "cd /tmp/x && cd && rm -rf proj", "rm -rf node_modules /c"):
    check(must in A, f"A phải có (ca biên): {must!r}")
for benign in ("SP=/tmp/claude-0/scratchpad; cd $SP/rv7 && rm -rf repos new", "cat transcript.txt"):
    check(benign not in A, f"A không được có: {benign!r}")
check("git branch -D ancient" not in A, "dòng có timestamp cũ hơn --since không được đọc")
check(cmds("G_rejected_not_asked") == {"ls -la", "cat data/bao-cao.csv"}, f"G sai (output thường có chữ 'doesn't want to proceed' không phải từ chối): {cmds('G_rejected_not_asked')}")
check("git branch -d wt-u1 wt-u2" not in A, "git branch -d (chữ thường) là xoá an toàn, không được vào A")
check("git branch -D wip-chua-gop" in A, "git branch -D (xoá cưỡng bức) phải vào A")
for benign in ("git -C .claude/worktrees/agent-a1b2c3d4e5f60718 status --short && git branch -D worktree-agent-a1b2c3d4e5f60718",
               "git branch -D worktree-agent-aeb4c21e13a20ddd0 2>&1; rm -rf .claude/worktrees/agent-aeb4c21e13a20ddd0 && git worktree prune",
               "cd /c/Users/admin/automarking && git branch -D worktree-agent-aeb4c21e13a20ddd0 2>&1; "
               "rm -rf .claude/worktrees/agent-aeb4c21e13a20ddd0 && git worktree prune",
               "rm -rf /c/Users/admin/automarking/.claude/worktrees/agent-abc123",
               "Remove-Item -Recurse -Force C:\\Users\\admin\\automarking\\.claude\\worktrees\\agent-abc123",
               "git branch -D worktree-agent-abc worktree-agent-def",
               "rm -rf ~/automarking/.claude/worktrees/agent-abc123/ ./.claude/worktrees/agent-def/src",
               "git branch --delete --force worktree-agent-abc >/dev/null 2>&1"):
    check(benign not in A, f"agent dọn worktree tạm của chính nó (đích ghi trọn) không phải lỗi: {benign!r}")
# Lead bỏ suy luận theo cd (và theo merge-base) ngày 18/10: các ca này từng vô hại nhờ suy luận đó, nay vẫn nghi.
# w7: đường có khoảng trắng không khớp được mẫu ghi trọn (mẫu không nhận khoảng trắng).
for must in ('for b in fix/ur-runner fix/us-stale fix/ual-alerts; do git merge-base --is-ancestor "refs/heads/$b" origin/trial/agent-team && git branch -D "$b"; done',
             "cd .claude/worktrees/agent-abc && rm -rf src",
             'Remove-Item -Recurse -Force "C:\\Users\\Ten Nguoi\\repo\\.claude\\worktrees\\agent-abc"'):
    check(must in A, f"lead bỏ suy luận theo cd: vẫn nghi: {must!r}")
# Review vòng 2: subshell, bash -c, eval, FOO=1 cd, time cd, `&`, dấu phẩy PowerShell, xargs, nhánh thường kèm theo,
# `..`, `.`, glob, agent-<không phải hex>, nhiều đích có một đích lạ, xargs ở thư mục tạm.
for must in ("(cd .claude/worktrees/agent-abc && npm run build) && rm -rf out", "(cd .claude/worktrees/agent-abc/ ); rm -rf src",
             "cd .claude/worktrees/agent-abc && bash -c 'cd ../../..; rm -rf src'",
             "cd .claude/worktrees/agent-abc && eval cd /; rm -rf home", "cd .claude/worktrees/agent-abc && FOO=1 cd / && rm -rf home",
             "cd .claude/worktrees/agent-abc && time cd / && rm -rf home", "cd .claude/worktrees/agent-abc/ & rm -rf src",
             "Remove-Item -Recurse -Force C:\\repo\\src,C:\\repo\\.claude\\worktrees\\agent-abc",
             "Remove-Item -Recurse -Force -LiteralPath C:\\repo\\src,C:\\repo\\.claude\\worktrees\\agent-abc",
             "Remove-Item -Recurse -Force C:\\repo\\.claude\\worktrees\\agent-abc,C:\\repo\\src",
             "echo main | xargs git branch -D worktree-agent-abc", "git branch -D worktree-agent-abc main",
             "git branch -D worktree-agent-abc >main", "rm -rf .claude/worktrees/agent-abc/..", "rm -rf .claude/worktrees/agent-abc/.",
             "rm -rf .claude/worktrees/agent-abc*", "rm -rf .claude/worktrees/agent-xyz", "rm -rf .claude/worktrees/agent-abc ~/x",
             "cd /tmp/x && ls / | xargs rm -rf", "xargs .claude/worktrees/agent-abc/rm -rf .claude/worktrees/agent-abc"):
    check(must in A, f"chỉ đích ghi trọn là worktree agent mới vô hại: vẫn nghi: {must!r}")
for must in ("rm -rf .claude/worktrees/agent-abc\\\n  src", "rm -rf .claude/worktrees/agent-abc\\; /home",
             "rm -rf .claude/worktrees/agent-abc\\| /home", "rm -rf .claude/worktrees/agent-abc/sub\\\n /home/u/proj",
             "rm -rf .claude/worktrees/agent-abc\\-old",
             "X=.claude/worktrees/agent-abc/home; IFS=c; rm -rf $X", "IFS=c; rm -rf .claude/worktrees/agent-abc/home",
             "Remove-Item -Path:C:\\proj\\* -Recurse -Force -Exclude C:\\proj\\.claude\\worktrees\\agent-abc",
             "D=/; D=.claude/worktrees/agent-abc true; rm -rf $D"):
    check(must in A, f"`\\` của bash, biến, IFS hay -Tên:giá-trị làm đích thật khác đích ghi: vẫn nghi: {must!r}")
for must in ("rm -rf dist\\\n  src", "rm -rf /tmp/x\\\n  src", "ls | xargs \\\n  rm -rf /tmp/x", "echo a\\\\\nrm -rf src"):
    check(must in A, f"nối dòng như bash trước khi tách lệnh: đích hay xargs ở dòng sau vẫn tính: {must!r}")
# Không thụt lề thì bash dán `src` vào đích trước: chỉ xoá /tmp/xsrc, vẫn trong thư mục tạm.
check("rm -rf /tmp/x\\\nsrc" not in A, "`\\` + xuống dòng không thụt lề nối thành một đích /tmp/xsrc: vô hại")
for must in ("rm -rf -- -important /tmp/x", "rm -rf /tmp/x -- -y"):
    check(must in A, f"token sau `--` là đích dù mở bằng `-`: {must!r}")
check("rm -rf -- /tmp/x" not in A, "bản thân `--` không phải đích: rm -rf -- /tmp/x vô hại")
# Chốt "không có đích ngoài cờ thì báo" của bản cũ phải giữ: thư mục suy từ cd có thể sai (subshell, cd .., cd lỗi)
# và bản cũ báo các ca này chỉ nhờ chốt đó.
for must in ("(cd /tmp && true); rm -rf -- -x", "cd dist && cd .. && rm -rf -- -x", "cd /tmp/w; rm -rf -- -x"):
    check(must in A, f"đích chỉ gồm token mở bằng `-` thì vẫn báo như bản cũ, dù cd trông lành: {must!r}")
WT = "/khong-co-tren-may/kitproj/.claude/worktrees/agent-abc"
AW = {(i["command"], i["cwd"]) for i in r["A_possible_misses"]}
# `rm -rf src` (w5) từng vô hại chỉ nhờ cwd của phiên là worktree agent. Lead chốt 18/10: cwd của phiên không phải cd
# tường minh, không làm thư mục xuất phát (lỗi chặn 1), nên ca này vẫn nghi như mọi `rm -rf src` khác.
for must in ("rm -rf src", "rm -rf $PROJECT_ROOT/src", 'rm -rf "$REPO/src"', 'rm -rf "$(git rev-parse --git-common-dir)"',
             "cd -- /home/u/proj && rm -rf src", "cd -P /home/u/proj && rm -rf src", "if cd /home/u/proj; then rm -rf src; fi",
             "for d in /home/u/proj; do cd $d; rm -rf src; done", "builtin cd /home/u/proj && rm -rf src",
             "ls /home/u/proj | xargs rm -rf", "rm -rf $SP/rv6"):
    check((must, WT) in AW, f"cwd của phiên là worktree agent không làm đích tương đối thành vô hại: {must!r}")
IN = "cd .claude/worktrees/agent-abc && "
for must in (IN + "rm -rf $PROJECT_ROOT/src", IN + 'rm -rf "$(git rev-parse --git-common-dir)"',
             IN + "rm -rf `git rev-parse --show-toplevel`", IN + "rm -rf +(.)/src", IN + "rm -rf {.,.}./src",
             IN + "cd -- /home/u/proj && rm -rf src", IN + "cd -P /home/u/proj && rm -rf src",
             "cd .claude/worktrees/agent-abc; if cd /home/u/proj; then rm -rf src; fi",
             "cd .claude/worktrees/agent-abc; for d in /home/u/proj; do cd $d; rm -rf src; done",
             IN + "builtin cd /home/u/proj && rm -rf src", IN + "ls /home/u/proj | xargs rm -rf"):
    check(must in A, f"sau cd vào worktree agent vẫn nghi: {must!r}")
for must in ("rm -rf .claude/worktrees/agent-abc/$REL", "rm -rf .claude/worktrees/agent-abc/`cat<p`",
             "rm -rf .claude/worktrees/agent-abc/{.,.}./quirky-mayer-c977af"):
    check(must in A, f"đường dẫn có worktree agent nhưng chứa biến, lệnh lồng hay brace vẫn nghi: {must!r}")
for must in ("git merge-base --is-ancestor a main && git -C ../khac branch -D a",
             "git -C ../khac merge-base --is-ancestor a main && git branch -D a",
             "git --git-dir=../khac/.git merge-base --is-ancestor a main && git branch -D a",
             "git merge-base --is-ancestor a main && git --work-tree=../khac branch -D a",
             "git merge-base --is-ancestor a a && git branch -D a"):
    check(must in A, f"merge-base trước khi xoá nhánh không làm lệnh thành vô hại: {must!r}")
check('echo "# drift" >> skill/agent-audit/mode.md ; cat skill/agent-audit/mode.md ; git checkout -- skill/agent-audit/mode.md' in A,
      "git checkout -- sau khi tự ghi thử vẫn phải ở A")
for must in ("git branch -D feature-x", "git branch -D worktree-agent-abc feature-x", "rm -rf .claude/worktrees",
             "rm -rf .claude/worktrees/quirky-mayer-c977af", "rm -rf .claude/worktrees/agent-abc/../..",
             "git merge-base --is-ancestor a main; git branch -D a", "git merge-base --is-ancestor a main && git branch -D b",
             "git merge-base --is-ancestor a main || git branch -D a", "! git merge-base --is-ancestor a main && git branch -D a",
             "cd && rm -rf proj", "cd .. && rm -rf src", "cd $D && rm -rf src"):
    check(must in A, f"A phải có (không phải worktree hay nhánh tạm của agent): {must!r}")
check("`ls -la`" in md and "bạn từ chối" in md.split("## G.")[1] and "auto mode chặn" in md.split("## G.")[1],
      "mục G phải ghi ai chặn: bạn hay auto mode/luật")
sg = r["stop_gate"]
check(sg["runs"] == 1 and sg["max_s"] == 125.0, f"Stop gate phải đo được 125s: {sg}")
check(sg["blocks"] == ["1/3"] and sg["released_after_max"] == 1, f"Stop gate chặn/nhả sai: {sg}")
check(len(r["hook_errors"]) == 1 and "command not found" in r["hook_errors"][0]["stderr"], f"lỗi hook: {r['hook_errors']}")
check("## A. Có thể guard bỏ sót:" in md and "## H." in md and "## F. Lỗi hook của kit: 1" in md, "báo cáo markdown thiếu mục")
# Chạy từ dự án chưa cài kit (bản plugin): dự án là thư mục hiện tại, guard chạy lại là guard của kit.
o = json.load(open(sys.argv[5], encoding="utf-8"))
plain = os.path.realpath(sys.argv[7])
check(os.path.realpath(o["project"]) == plain, f"chạy từ dự án khác thì báo cáo phải về dự án đó: {o['project']}")
check(o["replay"], "dự án chưa cài kit: phải chạy lại bằng guard của kit")
check({i["command"] for i in o["H_ran_unguarded"]} == {"git push --force origin feat/x"}, f"force-push chạy khi chưa có guard phải vào H: {o['H_ran_unguarded']}")
check({i["command"] for i in o["A_possible_misses"]} == {"danger-cmd now"}, f"mẫu riêng của dự án (.claude/audit-watch.txt) phải áp dụng: {o['A_possible_misses']}")
check(len(o["hook_errors"]) == 1 and "python3" in o["hook_errors"][0]["stderr"], f"lỗi hook của plugin (run-hook.sh) phải vào F: {o['hook_errors']}")
check(o["stop_gate"]["runs"] == 1 and o["stop_gate"]["max_s"] == 4.0, f"một lần Stop có cả bản dự án lẫn bản plugin (nhường) chỉ tính một lần chạy, lấy thời gian lâu nhất: {o['stop_gate']}")
# --all: đọc mọi dự án, mẫu riêng chỉ áp cho dự án khai báo nó.
al = json.load(open(sys.argv[6], encoding="utf-8"))
check(al["files"] == 3, f"--all phải đọc file phiên của mọi dự án: {al['files']}")
check({i["command"] for i in al["B_regressions"]} == {"echo dual-1", "echo dual-2"},
      f"hai bản ghi guard (dự án + plugin): một bản hỏi là đã hỏi, bất kể thứ tự: {al['B_regressions']}")
A = {i["command"] for i in al["A_possible_misses"]}
check("danger-cmd now" in A and "danger-cmd later" not in A, f"--all: mẫu riêng của dự án chỉ áp cho dự án đó: {A}")
check({i["command"] for i in al["H_ran_unguarded"]} == {"git push --force origin feat/x", "git reset --hard HEAD~1"}, f"--all: H phải gồm lệnh của cả hai dự án: {al['H_ran_unguarded']}")
check("plain proj" in sys.argv[8] and "mainrepo" in sys.argv[8], "--all: mỗi dòng báo cáo phải ghi dự án")
spec = importlib.util.spec_from_file_location("audit", "scripts/audit-agent.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
check(a.project_key("C:\\vnstock-trial") == "C--vnstock-trial", "tên thư mục phiên cho đường dẫn Windows")
check(a.project_key("/home/user") == "-home-user", "tên thư mục phiên cho đường dẫn Linux")
for cmd, want in (("rm -rf /tmp/x\\\nsrc", ["rm -rf /tmp/xsrc"]), ("echo a\\\\\nrm -rf src", ["echo a\\\\", "rm -rf src"])):
    got = [full for _p, full, _c, _s in a.segments(cmd)]
    check(got == want, f"segments nối dòng như bash (`\\` + xuống dòng bị bỏ, `\\\\` + xuống dòng là hai lệnh): {cmd!r} -> {got!r}")
# PowerShell nối dòng bằng backtick, `\` cuối dòng chỉ là dấu phân cách đường dẫn.
got = [full for _p, full, _c, _s in a.segments("Remove-Item -Recurse C:\\x\\\nsrc", "PowerShell")]
check(got == ["Remove-Item -Recurse C:\\x\\", "src"], f"PowerShell không nối dòng tại `\\`: {got!r}")
# Chỗ bash KHÔNG nối dòng: `\` trong comment là chữ, `\` cuối thân heredoc hay cuối dòng mở heredoc không nối qua ranh giới.
# Bản nối dòng đọc sai các ca này, bản không nối dòng vẫn bắt được.
for cmd in ("cd proj # vao thu muc \\\nrm -rf src ./node_modules", "cd proj;# x \\\nrm -rf src /tmp/x"):
    check(a.suspicious_labels(cmd, a.SUSPICIOUS), f"`\\` cuối comment là chữ: bash chạy rm ở dòng sau như lệnh riêng, ở thư mục proj: {cmd!r}")
check(a.suspicious_labels("bash <<'EOF'\ncd proj \\\nEOF\nrm -rf src ./node_modules", a.SUSPICIOUS),
      "thân heredoc đưa vào bash kết thúc ở EOF: `\\` cuối thân không nối với rm, rm chạy ở thư mục cũ")
check(a.suspicious_labels("cd node_modules <<'EOF' \\\nx\nEOF\nrm -rf src", a.SUSPICIOUS),
      "`\\` cuối dòng mở heredoc kéo `x` vào lệnh (cd node_modules x: cd lỗi), rm chạy ở thư mục cũ")
# `#` trong nháy không mở comment: bash vẫn nối dòng, `src` và `--force` ở dòng sau thuộc cùng lệnh.
for cmd in ("rm -rf \"/tmp/a #1\" \\\n  src", "git push -o merge_request.title=\"Fix #12\" origin feat \\\n  --force"):
    check(a.suspicious_labels(cmd, a.SUSPICIOUS), f"`#` trong nháy không phải comment: vẫn nối dòng, phải nghi: {cmd!r}")
# Thân heredoc đưa vào shell chạy ở shell con: cd trong thân không đổi thư mục của lệnh sau EOF. Ca này vẫn nghi
# nhờ bản không nối dòng: `\` còn dính vào thư mục cd (`node_modules \`).
check(a.suspicious_labels("bash <<'EOF'\ncd node_modules \\\nEOF\nrm -rf src", a.SUSPICIOUS),
      "cd trong thân heredoc chạy ở shell con, rm sau EOF chạy ở thư mục cũ")
check(not a.suspicious_labels("cd /tmp/w && bash <<'EOF'\nrm -rf y\nEOF", a.SUSPICIOUS),
      "shell con thừa hưởng thư mục: cd trước heredoc vẫn áp cho lệnh trong thân")
# Bản nối dòng chỉ thêm nghi ngờ: lệnh nghi khi đọc không nối dòng vẫn nghi, dù nối dòng dán dòng sau vào cd,
# vào thân heredoc hay làm nháy `'` ghép qua nhiều dòng.
for cmd in ("bash <<'EOF'\ncd node_modules \\\n  && npm ci\n# don't touch src\nEOF\ngit add -A && git commit -m 'wip'\nrm -rf src",
            "# don't do this\nrm -rf src\ncat > f <<'EOF' \\\n  && echo 'done'\nbody\nEOF", "cd /tmp/x \\\npopd\nrm -rf src"):
    check(a.suspicious_labels(cmd, a.SUSPICIOUS), f"bản nối dòng chỉ thêm nghi ngờ: lệnh nghi khi không nối dòng vẫn nghi: {cmd!r}")
# Mục I (bạn phải sửa agent) và J (chỉ số theo tuần).
import collections
lr = json.load(open(sys.argv[9], encoding="utf-8"))
lcode, lmd, ex = int(sys.argv[10]), sys.argv[11], json.load(open(sys.argv[12], encoding="utf-8"))
check(lcode == 0, f"audit thư mục mục I/J phải exit 0, được {lcode}")
lsg = lr["stop_gate"]
check(lsg["runs"] == 2 and lsg["blocks"] == ["1/3", "1/3"],
      f"E: hai dòng Stop gate không có uuid (khác giờ, khác cwd) là hai lần chạy, không được gộp: {lsg}")
I = lr.get("I_user_corrections") or []
kinds = collections.Counter(i.get("kind") for i in I)
check(kinds == {"interrupt": 1, "reject_note": 1, "correction": 3}, f"I phải có 1 ngắt, 1 từ chối kèm lời, 3 câu sửa: {dict(kinds)}")
check(bool(I) and I[0].get("kind") == "reject_note", f"I sắp theo giờ: lần từ chối tuần trước đứng đầu: {[i.get('kind') for i in I]}")
ints = [i for i in I if i.get("kind") == "interrupt"]
check(len(ints) == 1 and ints[0].get("doing") == "Bash: git push origin feat/x", f"ngắt phải ghi tool vừa gọi: {ints}")
rej = [i for i in I if i.get("kind") == "reject_note"]
check(len(rej) == 1 and rej[0].get("doing") == "Edit: /x/a.py" and rej[0].get("text") == "đừng đụng file này, sửa test trước",
      f"từ chối kèm lời phải ghi tool bị từ chối và lời của bạn: {rej}")
fix = {i.get("text") for i in I if i.get("kind") == "correction"}
check(fix == {"vẫn lỗi khi chạy check", "bạn quên chạy test rồi", "That's WRONG, I told you to use utf-8"},
      f"câu sửa: chỉ tin bạn gõ sau khi agent đã trả lời (kể cả <command-args>), không tin máy chèn, không câu hỏi thường: {fix}")
rows = lr.get("weekly") or []
W = {(w.get("week"), w.get("project")): w for w in rows}
ZERO = dict(prompts=0, interrupt=0, reject_note=0, correction=0, fixes=0, fixes_per_10=None, stop_blocks=0,
            verifier_pass=0, verifier_fail=0, verifier_inconclusive=0, reviewer_blocked=0, reviewer_total=0)
def row(week, proj, **want):
    want = dict(ZERO, **want)
    got = W.get((week, proj)) or {}
    bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
    check(not bad, f"J dòng {week} {proj}: (được, cần) {bad}")
row(ex["w1"], "learnrepo", prompts=3, reject_note=1, fixes=1, fixes_per_10=3.3, stop_blocks=1)
row(ex["w2"], "learnrepo", prompts=4, interrupt=1, correction=2, fixes=3, fixes_per_10=7.5, verifier_pass=1, reviewer_blocked=1, reviewer_total=2)
row(ex["w2"], "winproj", prompts=2, correction=1, fixes=1, fixes_per_10=5.0)
row(ex["w2"], "otherproj", stop_blocks=1)
order = [(w.get("week"), w.get("project")) for w in rows]
check(order == [(ex["w1"], "learnrepo"), (ex["w2"], "learnrepo"), (ex["w2"], "otherproj"), (ex["w2"], "winproj")],
      f"J phải có 4 dòng, tuần cũ trước, trong tuần xếp theo tên dự án: {order}")
check("## I. Bạn phải sửa agent: 5" in lmd and "## J. Chỉ số theo tuần" in lmd, "markdown thiếu mục I hoặc J")
check(-1 < lmd.find("## F.") < lmd.find("## I.") < lmd.find("## J."), "mục I và J phải đứng sau F")
lines = lmd.splitlines()
first = lambda p: next((x for x in lines if x.startswith(p)), "")
ng = first("- [ngắt] ")
check(ex["w2_local"] in ng and "đang: " in ng and "Bash: git push origin feat/x" in ng and "@ " + ex["sub"] in ng,
      f"dòng ngắt phải có giờ địa phương, việc đang làm và cwd (--all): {ng!r}")
tc = first("- [từ chối kèm lời] ")
check('"đừng đụng file này, sửa test trước"' in tc and "đang: " in tc and "Edit: /x/a.py" in tc, f"dòng từ chối kèm lời: {tc!r}")
cs = [x for x in lines if x.startswith("- [câu sửa] ")]
check(len(cs) == 3 and any('"vẫn lỗi khi chạy check"' in x for x in cs), f"dòng câu sửa: {cs}")
check("| Tuần | Dự án | Lượt hỏi | Bạn sửa (ngắt/lời/câu) | Sửa trên 10 lượt | Stop gate chặn | Verifier P/F/I | Reviewer chặn/tổng |" in lmd,
      "J thiếu tiêu đề bảng")
for want in (f"| {ex['w1']} | learnrepo | 3 | 1 (0/1/0) | 3.3 | 1 | 0/0/0 | 0/0 |",
             f"| {ex['w2']} | learnrepo | 4 | 3 (1/0/2) | 7.5 | 0 | 1/0/0 | 1/2 |",
             f"| {ex['w2']} | otherproj | 0 | 0 (0/0/0) | - | 1 | 0/0/0 | 0/0 |",
             f"| {ex['w2']} | winproj | 2 | 1 (0/0/1) | 5.0 | 0 | 0/0/0 | 0/0 |"):
    check(want in lmd, f"J thiếu dòng: {want}")
check(-1 < lmd.find(f"| {ex['w1']} |") < lmd.find(f"| {ex['w2']} |"), "J: tuần cũ phải đứng trước")
check("## J." in sys.argv[8] and "Chưa có dữ liệu." in sys.argv[8].split("## J.")[-1], "J không có sự kiện nào thì in 'Chưa có dữ liệu.'")
# Ca reviewer tìm ra ở mục I/J: mỗi ca một dự án.
rv = json.load(open(sys.argv[13], encoding="utf-8"))
RW = {w.get("project"): w for w in rv.get("weekly") or []}
said = lambda proj: sorted(i.get("text") for i in rv.get("I_user_corrections") or [] if i.get("kind") == "correction" and i.get("project") == proj)
w = RW.get("ideproj") or {}
check(w.get("prompts") == 4, f"tin gõ trong IDE (ngữ cảnh máy chèn đứng trước) và HTML dán vào vẫn là lượt hỏi; bash/task/local-command thì không: {w}")
check(said("ideproj") == sorted(["sai rồi, đừng sửa file này", "bạn quên chạy test", '<div class="err">Nút này vẫn sai màu</div> sửa giúp']),
      f"câu sửa trong tin IDE: bỏ ngữ cảnh máy chèn, giữ lời bạn: {said('ideproj')}")
def rrow(proj, why, **want):
    got = RW.get(proj) or {}
    bad = {k: (got.get(k), v) for k, v in dict(ZERO, **want).items() if got.get(k) != v}
    check(not bad, f"J dòng {proj} ({why}): (được, cần) {bad}")
rrow("dupproj", "dòng có mặt ở hai file phiên, chung uuid hoặc trùng nội dung khi không có uuid, chỉ đếm một lần",
     prompts=4, interrupt=1, reject_note=1, correction=2, fixes=4, fixes_per_10=10.0, stop_blocks=2, verifier_pass=1)
dupI = collections.Counter((i.get("kind"), i.get("text")) for i in rv.get("I_user_corrections") or [] if i.get("project") == "dupproj")
check(dupI == {("reject_note", "đừng push"): 1, ("interrupt", None): 1, ("correction", "vẫn sai, làm lại"): 1, ("correction", "bạn nhầm rồi"): 1},
      f"I: mỗi lần sửa một dòng dù phiên có hai bản chép: {dict(dupI)}")
dsg = rv["stop_gate"]
check(dsg["runs"] == 1 and dsg["blocks"] == ["1/3", "2/3"] and dsg["released_after_max"] == 1,
      f"E: phiên có hai bản chép thì dòng Stop gate chung uuid (chạy, chặn, nhả) chỉ đếm một lần: {dsg}")
check(len(rv["hook_errors"]) == 1, f"F: phiên có hai bản chép thì dòng lỗi hook chung uuid chỉ đếm một lần: {rv['hook_errors']}")
g = [i.get("cwd") for i in rv.get("G_rejected_not_asked") or [] if i.get("command") == "git push origin feat/w"]
wr = [(i.get("kind"), i.get("cwd")) for i in rv.get("I_user_corrections") or [] if i.get("text") == "đừng push w"]
wrJ = sorted((w.get("project"), w.get("prompts"), w.get("reject_note")) for w in rv.get("weekly") or [] if w.get("project", "").startswith("wr"))
check(len(g) == 1 and wr == [("reject_note", g[0])] and wrJ == [(g[0].rsplit("/", 1)[-1], 1, 1)],
      f"hai bản chép khác cwd: I/J đếm một lần và quy về cùng cwd với mục G: G {g}, I {wr}, J {wrJ}")
check(said("rxproj") == sorted(["ko đúng, vẫn chưa được", "đã bảo là chạy test trước"]),
      f"câu sửa: 'đã bảo vệ/bảo mật', 'vẫn chưa được merge' không khớp, 'ko đúng' có khớp: {said('rxproj')}")
fixes_of = lambda proj: [i for i in rv.get("I_user_corrections") or [] if i.get("project") == proj]
check(fixes_of("rjproj") == [], f"bấm No ở hộp hỏi: dấu ngắt đi ngay sau lần từ chối không phải ngắt: {fixes_of('rjproj')}")
rrow("rjproj", "từ chối không kèm lời không vào mục I", prompts=2, fixes_per_10=0.0)
rjG = sorted((i.get("command"), i.get("rejected_by")) for i in rv.get("G_rejected_not_asked") or [] if i.get("cwd") == "/khong-co-tren-may/rjproj")
check(rjG == [("git push --force origin khong-co-nhanh-nay", "người"), ("git push --force origin trial/agent-team", "người")],
      f"lần từ chối vẫn được đếm ở mục G: {rjG}")
esc = [(i.get("kind"), i.get("doing")) for i in fixes_of("escproj")]
check(esc == [("interrupt", "Bash: ls docs")], f"Esc lúc model đang viết, không có từ chối: 1 ngắt: {esc}")
rrow("escproj", "Esc lúc model đang viết", prompts=1, interrupt=1, fixes=1, fixes_per_10=10.0)
rjn = [(i.get("kind"), i.get("text")) for i in fixes_of("rjnoteproj")]
check(rjn == [("reject_note", "đẩy lên nhánh feat thôi")], f"từ chối kèm lời rồi dấu ngắt: 1 từ chối kèm lời, 0 ngắt: {rjn}")
rrow("rjnoteproj", "từ chối kèm lời rồi dấu ngắt", prompts=1, reject_note=1, fixes=1, fixes_per_10=10.0)
rjp = [(i.get("kind"), i.get("doing")) for i in fixes_of("rjpromptproj")]
check(rjp == [("interrupt", "Bash: git push --force origin feat/z")], f"từ chối, lượt hỏi mới rồi Esc trước khi agent trả lời: 1 ngắt: {rjp}")
rrow("rjpromptproj", "từ chối, lượt hỏi mới rồi Esc", prompts=2, interrupt=1, fixes=1, fixes_per_10=5.0)
ed = [(i.get("kind"), i.get("doing")) for i in fixes_of("editproj")]
check(ed == [("interrupt", "Edit: README.md")], f"bấm No ở Edit (không có ở D/G) rồi dấu ngắt: vẫn 1 ngắt: {ed}")
rrow("editproj", "từ chối Edit rồi dấu ngắt", prompts=1, interrupt=1, fixes=1, fixes_per_10=10.0)
rja = [(i.get("kind"), i.get("doing")) for i in fixes_of("rjanswerproj")]
check(rja == [("interrupt", "Bash: git push --force origin feat/q")], f"từ chối, agent trả lời rồi Esc: 1 ngắt: {rja}")
rrow("rjanswerproj", "từ chối, agent trả lời rồi Esc", prompts=1, interrupt=1, fixes=1, fixes_per_10=10.0)
rjt = [(i.get("kind"), i.get("doing")) for i in fixes_of("rjtaskproj")]
check(rjt == [("interrupt", "Bash: git push --force origin feat/t")],
      f"từ chối kèm dấu ngắt, tin task nền rồi Esc trước khi agent viết: dấu ngắt thứ hai là 1 ngắt: {rjt}")
rrow("rjtaskproj", "từ chối, dấu ngắt, tin task nền rồi Esc", prompts=1, interrupt=1, fixes=1, fixes_per_10=10.0)
check(fixes_of("turonlyproj") == [], f"bấm No chỉ có toolUseResult: dấu ngắt đi kèm không phải ngắt: {fixes_of('turonlyproj')}")
rrow("turonlyproj", "từ chối chỉ có toolUseResult không vào mục I", prompts=2, fixes_per_10=0.0)
turG = sorted((i.get("command"), i.get("rejected_by")) for i in rv.get("G_rejected_not_asked") or [] if i.get("cwd") == "/khong-co-tren-may/turonlyproj")
check(turG == [("git push --force origin feat/t1", "người"), ("git push --force origin feat/t2", "người")],
      f"từ chối chỉ có toolUseResult (không có is_error, hoặc nội dung lạ) vẫn vào mục G: {turG}")
wt = sorted((p, w.get("prompts")) for p, w in RW.items() if p in ("wtproj", "mainproj", "feat-a", "src", "pkg", "wt-elsewhere", "feat-c"))
check(wt == [("mainproj", 2), ("wtproj", 2)], f"J: worktree (.claude/worktrees, hoặc .git là file trỏ về repo chính) quy về repo chính: {wt}")
for f in fails:
    print("✘", f, file=sys.stderr)
if fails:
    print(f"✘ audit: {len(fails)}/{total} test đỏ", file=sys.stderr)
    sys.exit(1)
print(f"✔ audit: {total} test xanh")
PYEOF
status=$?

# Không thụt lùi: sửa phân tích lệnh đã nhiều lần âm thầm làm mục A bỏ sót lệnh mà bản trước vẫn báo (1e9882a phải vá
# 3 lần, PR #1 bị chặn 3 vòng), lần nào cũng chỉ lộ ra nhờ reviewer tự so nhãn giữa hai bản. Đây là đúng phép so đó, trên
# mọi lệnh fixture ở trên và một bộ fuzz cố định. Chỉ chạy trong repo kit (có install-kit.sh, file không chép sang dự án):
# ở dự án cài kit, bản trước là bản kit cũ đã commit nên nâng cấp qua một lần thu hẹp có chủ ý sẽ đỏ, mà NARROWING_OK lại
# nằm trong file của kit. Bản trước: AUDIT_BASE_REF nếu đặt; không thì HEAD khi audit-agent.py đang sửa dở; merge-base với
# origin/HEAD khi có và khác HEAD (soát mọi commit của nhánh, không chỉ commit cuối); còn lại HEAD^ (PR trong CI thường
# không có origin/HEAD: HEAD là merge commit, cha đầu là đầu nhánh base).
ref="${AUDIT_BASE_REF:-}" why="AUDIT_BASE_REF" skip="" miss=""
if [ ! -f scripts/install-kit.sh ]; then
  skip="chỉ chạy trong repo kit"
elif ! git rev-parse --git-dir >/dev/null 2>&1; then
  skip="không có git hoặc không ở trong repo git"
elif [ -z "$ref" ]; then
  git diff --quiet HEAD -- scripts/audit-agent.py 2>/dev/null
  case $? in
    0) ref="$(git merge-base HEAD origin/HEAD 2>/dev/null)" why="merge-base với origin/HEAD"
       if [ -z "$ref" ] || [ "$ref" = "$(git rev-parse HEAD)" ]; then ref="HEAD^" why="HEAD^"; fi ;;
    1) ref="HEAD" why="HEAD, audit-agent.py đang sửa dở" ;;
    *) skip="repo chưa có commit" ;;
  esac
fi
if [ -z "$skip" ] && ! git rev-parse -q --verify "$ref^{commit}" >/dev/null; then
  miss="không có ref $ref"
elif [ -z "$skip" ] && ! git show "$ref:./scripts/audit-agent.py" >"$tmp/audit-base.py" 2>/dev/null; then
  miss="không có scripts/audit-agent.py ở $ref"
elif [ -z "$skip" ]; then
  ref="$(git rev-parse --short "$ref^{commit}")"
fi
# Ref tự chọn mà thiếu (clone nông) thì bỏ qua; AUDIT_BASE_REF do người đặt có chủ ý, sai thì đỏ.
if [ -n "$miss" ] && [ -n "${AUDIT_BASE_REF:-}" ]; then
  printf '✘ audit: AUDIT_BASE_REF=%s không phải ref có scripts/audit-agent.py (%s)\n' "$AUDIT_BASE_REF" "$miss" >&2
  status=1
elif [ -n "$skip$miss" ]; then
  printf '• audit: bỏ qua so nhãn với bản trước (%s)\n' "$skip$miss"
elif git diff --quiet "$ref" -- scripts/audit-agent.py 2>/dev/null; then
  printf '• audit: audit-agent.py giống hệt bản ở %s (%s), bỏ qua so nhãn\n' "$ref" "$why"
else
  "$py" -I -B - "$tmp/audit-base.py" "$tmp" "$ref ($why)" <<'PYEOF' || status=1
import glob, importlib.util, json, os, random, sys
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding="utf-8")  # -I bỏ qua PYTHONIOENCODING
base_file, tmp, ref = sys.argv[1:4]
# Chỉ thêm khi CHỦ Ý thu hẹp mục A (người dùng than báo thừa): (tool, lệnh, "lý do"). Ghi đúng từng lệnh, không dùng
# mẫu, để người review đọc được hết những lệnh vừa thành vô hại.
NARROWING_OK = [
]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
new = load("audit_head", "scripts/audit-agent.py")
try:
    old = load("audit_base", base_file)
except Exception as exc:  # bản trước hỏng thì không có gì để thụt lùi
    print(f"• audit: bỏ qua so nhãn với bản trước (không nạp được bản ở {ref}: {exc!r})")
    sys.exit(0)
def shell_calls(x):
    """(tool, lệnh) của mọi tool_use Bash/PowerShell nằm trong x."""
    if isinstance(x, list):
        for v in x:
            yield from shell_calls(v)
    elif isinstance(x, dict):
        inp = x.get("input")
        if x.get("type") == "tool_use" and x.get("name") in ("Bash", "PowerShell") and isinstance(inp, dict) \
                and isinstance(inp.get("command"), str):
            yield x["name"], inp["command"]
        for v in x.values():
            yield from shell_calls(v)
fixture = []
for f in sorted(glob.glob(os.path.join(tmp, "**", "*.jsonl"), recursive=True)):
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                fixture += shell_calls(json.loads(line))
            except ValueError:
                pass  # dòng hỏng có chủ ý của fixture
# Fuzz cố định: 1–5 dòng ghép từ lõi nguy hiểm và các cấu trúc shell từng làm phân tích đọc sai (nối dòng, comment,
# heredoc đưa vào shell / dữ liệu / chưa đóng, cd, subshell, biến, xargs, `--`, worktree agent).
CORE = ["rm -rf src", "rm -rf -- -x", "rm -rf dist\\\n  src", "git push --force origin main", "git reset --hard",
        "git clean -fd", "git branch -D x", "Remove-Item -Recurse -Force src", "rd /s /q src"]
STEP = ["cd proj", "cd -P /home/u/proj", "cd /tmp/w", "cd dist", "cd ..", "cd", "pushd dist", "popd", "(cd /tmp && true)",
        "( cd dist )", "cd .claude/worktrees/agent-abc", "rm -rf .claude/worktrees/agent-abc",
        "rm -rf -- .claude/worktrees/agent-abc", "S=/tmp/x", "rm -rf $S", "ls | xargs rm -rf", "echo 'a b'", 'echo "a b"',
        "git commit -m 'wip'", "true"]
LINE = ["bash <<'EOF'", "cat <<EOF | sh", "cat > f <<'EOF'", "EOF", "# x \\", "# don't"]
TAIL = ["", "", "", "", " \\", " \\\\", " # x \\", " # don't"]
rnd = random.Random(1)
def line():
    if rnd.random() < 0.25:
        return rnd.choice(LINE)
    s = rnd.choice([" && ", "; ", " || ", " | "]).join(rnd.choice(CORE + STEP) for _ in range(rnd.randint(1, 2)))
    return ("(" + s + ")" if rnd.random() < 0.1 else s) + rnd.choice(TAIL)
fuzz = ["\n".join(line() for _ in range(rnd.randint(1, 5))) for _ in range(3000)]
pairs = list(dict.fromkeys(fixture + [(tool, c) for c in fuzz for tool in ("Bash", "PowerShell")]))
ok = {(tool, c) for tool, c, _why in NARROWING_OK}
in_fixture = set(fixture)
lost, crash, base_err, fixture_err, relabeled = [], [], [], [], 0
for tool, c in pairs:
    try:
        base = set(old.suspicious_labels(c, old.SUSPICIOUS, tool))
    except Exception as exc:
        base = exc
    try:
        head = set(new.suspicious_labels(c, new.SUSPICIOUS, tool))
    except Exception as exc:
        crash.append(f"{tool} {c!r}: {exc!r}")
        head = None
    if isinstance(base, Exception):
        base_err.append(f"{tool} {c!r}: {base!r}")
        if head is not None and (tool, c) in in_fixture:
            fixture_err.append(base_err[-1])
    elif head is not None and base - head:
        # Mục A chỉ xét lệnh còn nhãn nào không (tên nhãn chỉ để hiển thị): còn nhãn thì mục A vẫn báo, chỉ đếm.
        if head:
            relabeled += 1
        elif (tool, c) not in ok:
            lost.append((len(c), tool, c, sorted(base)))
# Bản trước ném lỗi ở mọi lệnh (vd đổi chữ ký hay tên suspicious_labels mà lời gọi ở trên chỉ khớp bản mới) thì phép so
# xanh giả. Chỉ bỏ qua lỗi của bản trước ở lệnh fuzz lẻ tẻ (bản cũ có thể crash, vd byte NUL).
uncallable = len(base_err) == len(pairs) or fixture_err
if not fixture:
    print("✘ audit: so nhãn không thấy lệnh fixture nào: bước này phải chạy sau khi mọi fixture đã sinh", file=sys.stderr)
for x in crash[:10]:
    print("✘ audit: suspicious_labels ném lỗi:", x, file=sys.stderr)
if uncallable:
    print(f"✘ audit: không gọi được bản ở {ref}: lời gọi bản đó ném lỗi ở {len(base_err)}/{len(pairs)} cặp lệnh/tool, "
          f"{len(fixture_err)} lệnh fixture mà bản này chạy được. Lỗi đầu tiên: {(fixture_err or base_err)[0]}", file=sys.stderr)
    print("  Đổi chữ ký hay tên suspicious_labels thì sửa lời gọi trong bước so này sao cho gọi được cả hai bản (bản trước "
          "theo chữ ký cũ, bản này theo chữ ký mới), đừng chỉ sửa cho khớp bản mới: không gọi được bản trước thì không so "
          "được gì.", file=sys.stderr)
if lost:
    print(f"✘ audit: mục A sẽ bỏ sót {len(lost)} lệnh mà bản ở {ref} vẫn báo (bản này hết nhãn nghi ngờ), ngắn nhất trước:",
          file=sys.stderr)
    for _n, tool, c, labels in sorted(lost)[:None if os.environ.get("AUDIT_LOST_ALL") else 10]:
        print(f"  {tool} {c!r}: bản trước báo {', '.join(labels)}", file=sys.stderr)
    print("  Sửa phân tích lệnh không được làm mục A bỏ sót lệnh bản trước vẫn báo. Đọc thêm theo cách cũ rồi lấy hợp (như "
          "suspicious_labels làm với nối dòng), hoặc giữ chốt cũ (như benign_delete với `--`). Nếu chủ ý thu hẹp thì "
          "thêm đúng lệnh vào NARROWING_OK kèm lý do (AUDIT_LOST_ALL=1 in đủ danh sách để soát).", file=sys.stderr)
if lost or crash or not fixture or uncallable:
    sys.exit(1)
print(f"✔ audit: mục A không bỏ sót lệnh nào bản ở {ref} báo: {len(pairs)} cặp lệnh/tool, {len(in_fixture)} từ fixture, "
      f"{relabeled} lệnh đổi nhãn nhưng vẫn nghi")
PYEOF
fi

# Bất biến khi có bản chép: worker khởi động lại hay resume chép phiên sang file khác, các dòng giữ uuid. Bộ đếm cộng dồn
# đếm chúng hai lần; đã vá từng bộ một (3e86d90 mục I/J, PR #1 mục E/F, rồi old_entries_skipped) vì không test nào canh
# mọi bộ đếm cùng lúc. Bước này chạy lại mọi thư mục phiên ở trên (A, dòng thiếu uuid được gán uuid tất định) và A kèm
# một bản chép đầy đủ (B): báo cáo phải y hệt, trừ files, transcripts, khoá file (đường dẫn đọc sau cùng) và bad_lines.
inv="$tmp/inv"
"$py" - "$tmp" "$inv" <<'PYEOF'
import json, os, shutil, sys
tmp, inv = sys.argv[1:3]
a = os.path.join(inv, "a")
for n in sorted(os.listdir(tmp)):
    src = os.path.join(tmp, n)
    if n != "inv" and os.path.isdir(src) and any(f.endswith(".jsonl") for _r, _d, fs in os.walk(src) for f in fs):
        shutil.copytree(src, os.path.join(a, n), symlinks=True)  # copy2: giữ mtime (--since lọc file theo mtime)
if not os.path.isdir(a):
    sys.exit("✘ audit: bước bản chép không thấy thư mục phiên nào: phải chạy sau khi mọi fixture đã sinh")
for root, _dirs, fs in os.walk(a):
    for f in fs:
        if not f.endswith(".jsonl"):
            continue
        p = os.path.join(root, f)
        st = os.stat(p)
        rel = os.path.relpath(p, a).replace(os.sep, "/")
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()
        for i, line in enumerate(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue  # dòng hỏng giữ nguyên
            if isinstance(e, dict) and not (isinstance(e.get("uuid"), str) and e["uuid"]):
                e["uuid"] = f"{rel}:{i + 1}"
                lines[i] = json.dumps(e, ensure_ascii=False) + "\n"
        with open(p, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
for n in ("goc", "chep"):
    shutil.copytree(a, os.path.join(inv, "b", n))
PYEOF
built=$?
./scripts/audit-agent.sh --transcripts "$inv/a" --since 30 --no-replay --json > "$inv/a.json"
acode=$?
./scripts/audit-agent.sh --transcripts "$inv/b" --since 30 --no-replay --json > "$inv/b.json"
bcode=$?
"$py" - "$inv" "$built" "$acode" "$bcode" <<'PYEOF' || status=1
import json, os, sys
inv, codes = sys.argv[1], [int(x) for x in sys.argv[2:5]]
if codes != [0, 0, 0]:
    sys.exit(f"✘ audit: bước bản chép không chạy được (dựng, audit A, audit B exit {codes})")
raw = [json.load(open(os.path.join(inv, n + ".json"), encoding="utf-8")) for n in "ab"]
def norm(x):
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items() if k != "file"}
    return [norm(v) for v in x] if isinstance(x, list) else x
# bad_lines: dòng JSON hỏng không có uuid nên không khử trùng được, ở B bị đếm hai lần và không tránh được.
a, b = ({k: v for k, v in norm(r).items() if k not in ("files", "transcripts", "bad_lines")} for r in raw)
fails = []
if raw[1]["files"] != 2 * raw[0]["files"]:
    fails.append(f"B phải đọc gấp đôi số file của A: A {raw[0]['files']}, B {raw[1]['files']}")
# Chỉ canh được bộ đếm mà fixture chạm tới: bộ nào rỗng ở A thì phép so vô nghĩa với nó.
idle = [k for k, v in (("shell_commands", a["shell_commands"]), ("old_entries_skipped", a["old_entries_skipped"]),
                       ("hook_errors", a["hook_errors"]), ("stop_gate.runs", a["stop_gate"]["runs"]),
                       ("I_user_corrections", a["I_user_corrections"]), ("weekly", a["weekly"])) if not v]
if idle:
    fails.append(f"fixture không chạm tới bộ đếm: {', '.join(idle)}")
def brief(v):
    s = f"[{len(v)} mục]" if isinstance(v, list) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 200 else s[:199] + "…"
diff = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
for k in diff:
    fails.append(f"{k}: A {brief(a.get(k))}, B {brief(b.get(k))}")
    if isinstance(a.get(k), list) and isinstance(b.get(k), list):
        i = next((i for i, (x, y) in enumerate(zip(a[k], b[k])) if x != y), None)
        if i is not None:
            fails[-1] += f"\n    mục {i} khác: A {brief(a[k][i])}, B {brief(b[k][i])}"
if fails:
    print("✘ audit: báo cáo đổi khi mọi file phiên có thêm một bản chép (A: fixture, B: A + một bản chép):", file=sys.stderr)
    for f in fails:
        print("  " + f, file=sys.stderr)
    if diff:
        print("  Bộ đếm mới phải khoá theo uuid của dòng (xem add_event, stop_runs…), không cộng dồn: phiên có bản chép "
              "ở file khác.", file=sys.stderr)
    sys.exit(1)
dirs = sorted(os.listdir(os.path.join(inv, "a")))
print(f"✔ audit: báo cáo không đổi khi mọi file phiên có thêm một bản chép ({raw[0]['files']} file từ {', '.join(dirs)})")
PYEOF
exit "$status"
