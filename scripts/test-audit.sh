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
"$py" - "$tmp/t" "$root" "$tmp/mainrepo" <<'PYEOF'
import json, os, sys, time
d, cwd = sys.argv[1], sys.argv[2]
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
call("m1", "git push", where=sys.argv[3])
# Claude Code trên Windows (2.1.296) không ghi kết quả guard vào file phiên: suy từ hộp hỏi.
call("n1", "git push --force origin y", result="rejected")                # bạn từ chối ở hộp hỏi -> D
call("n2", "git push -u origin main", pd={"decision": "accept", "source": "user_temporary"})
# Báo cáo desktop 16/10: branch -d (chữ thường, xoá an toàn) bị báo nhầm; G không ghi ai chặn.
call("b1", "git branch -d wt-u1 wt-u2")
call("b2", "git branch -D wip-chua-gop")
call("g2", "cat data/bao-cao.csv", result="denied", pd={"decision": "reject", "source": "config", "reasonType": "classifier"})  # bạn duyệt -> C, không phải H                                 # push lúc đang ở main, không khớp mẫu chữ
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

"$py" - "$out" "$code" "$nofile" "$md" "$other" "$all" "$plain" "$allmd" <<'PYEOF'
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
for f in fails:
    print("✘", f, file=sys.stderr)
if fails:
    print(f"✘ audit: {len(fails)}/{total} test đỏ", file=sys.stderr)
    sys.exit(1)
print(f"✔ audit: {total} test xanh")
PYEOF
