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
    user(T2, sub, [text("[Request interrupted by user for tool use]")]),
    user(T2, sub, [text("vẫn lỗi khi\nchạy   check")], origin=HUMAN),
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
# Mục I (bạn phải sửa agent) và J (chỉ số theo tuần).
import collections
lr = json.load(open(sys.argv[9], encoding="utf-8"))
lcode, lmd, ex = int(sys.argv[10]), sys.argv[11], json.load(open(sys.argv[12], encoding="utf-8"))
check(lcode == 0, f"audit thư mục mục I/J phải exit 0, được {lcode}")
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
g = [i.get("cwd") for i in rv.get("G_rejected_not_asked") or [] if i.get("command") == "git push origin feat/w"]
wr = [(i.get("kind"), i.get("cwd")) for i in rv.get("I_user_corrections") or [] if i.get("text") == "đừng push w"]
wrJ = sorted((w.get("project"), w.get("prompts"), w.get("reject_note")) for w in rv.get("weekly") or [] if w.get("project", "").startswith("wr"))
check(len(g) == 1 and wr == [("reject_note", g[0])] and wrJ == [(g[0].rsplit("/", 1)[-1], 1, 1)],
      f"hai bản chép khác cwd: I/J đếm một lần và quy về cùng cwd với mục G: G {g}, I {wr}, J {wrJ}")
check(said("rxproj") == sorted(["ko đúng, vẫn chưa được", "đã bảo là chạy test trước"]),
      f"câu sửa: 'đã bảo vệ/bảo mật', 'vẫn chưa được merge' không khớp, 'ko đúng' có khớp: {said('rxproj')}")
wt = sorted((p, w.get("prompts")) for p, w in RW.items() if p in ("wtproj", "mainproj", "feat-a", "src", "pkg", "wt-elsewhere", "feat-c"))
check(wt == [("mainproj", 2), ("wtproj", 2)], f"J: worktree (.claude/worktrees, hoặc .git là file trỏ về repo chính) quy về repo chính: {wt}")
for f in fails:
    print("✘", f, file=sys.stderr)
if fails:
    print(f"✘ audit: {len(fails)}/{total} test đỏ", file=sys.stderr)
    sys.exit(1)
print(f"✔ audit: {total} test xanh")
PYEOF
