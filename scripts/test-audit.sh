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
# Đích còn biến chưa biết, lệnh lồng hay brace: bash thay trước khi rm chạy, kết quả không phải đường tương đối với thư mục cd.
call("bc1", "cd /tmp/x && rm -rf $D/src")                               # D chưa gán: bash xoá /src
call("bc2", "cd /tmp/x && rm -rf `pwd`src")                             # bash xoá /tmp/xsrc: lệnh lồng cho đường tuyệt đối
call("bc3", "cd /tmp/x && rm -rf {/,}src")                              # brace: bash xoá /src và ./src
call("bc4", "cd /tmp/x && rm -rf $(git rev-parse --show-toplevel)/src") # xoá src ở gốc repo
# rm của BSD/macOS (getopt POSIX, không hoán vị) thôi nhận cờ ở toán hạng đầu tiên: token sau đó là đích dù mở bằng `-`.
# Không áp cho PowerShell (`rm` là Remove-Item, tham số đứng sau đích được) và cmd (`rd /s`), trừ khi chạy qua wsl.
call("bc5", "rm -rf /tmp/x -important")                                 # macOS xoá cả ./-important
call("bc6", "wsl rm -rf /tmp/x -important", tool="PowerShell")          # rm chạy trong Linux: đọc như lệnh Bash
call("bc7", "rm C:\\tmp\\x -Recurse", tool="PowerShell")                # vô hại: -Recurse là tham số của Remove-Item
call("bc8", "rd /s /q C:\\tmp\\x")                                       # vô hại: /s /q là cờ của cmd
# `/` cuối đích làm rm đi theo symlink ở thành phần cuối (`stat link` → symbolic link, `stat link/` → directory): xoá nội dung
# thư mục mà link trỏ tới, dù tên hay thư mục cd trông như thư mục tạm. Đích ghi trọn là worktree agent vẫn được `/` cuối (d5).
call("bc9", "rm -rf /tmp/link/")
call("bc10", "cd /tmp/x && rm -rf link/")
call("bc11", "rm -rf node_modules/")
# Thư mục cd chỉ áp cho lệnh nối sau nó bằng `&&` trong cùng phạm vi. Các ca sau, bash chạy rm ở thư mục dự án.
call("cx1", "(cd /tmp && true); rm -rf src")                            # cd trong subshell
call("cx2", "(cd /tmp && true) && rm -rf src")
call("cx3", "cd dist && cd .. && rm -rf src")                           # về lại thư mục dự án
call("cx4", "cd /tmp/w; rm -rf src")                                    # cd lỗi thì lệnh sau `;`, xuống dòng, `||` vẫn chạy
call("cx5", "cd /tmp/w\nrm -rf src")
call("cx6", "cd /tmp/w || true; rm -rf src")
call("cx7", "cd node_modules/ x; rm -rf src")                           # cd nhiều tham số: lỗi
call("cx8", "cd /tmp/x & rm -rf src")                                   # cd chạy nền ở shell con
call("cx9", "cd /tmp/x && rm -rf y")                                    # vô hại: rm chạy trong /tmp/x
call("cx10", "cd /tmp/x &&\nrm -rf y")                                  # bash cho xuống dòng sau `&&`
call("cx11", "(cd /tmp/x && rm -rf foo)")
call("cx12", "cd dist && cd .'.' && rm -rf src")                        # nháy và `\` không che được `..`
call("cx13", "cd dist && cd .\\. && rm -rf src")
call("cx14", 'cd /tmp/x && cd "-L" && rm -rf src')                      # vẫn là cờ: cd -L về $HOME
# Không biết thư mục sau các lệnh này, bash chạy rm ở thư mục dự án (hay ở /): đích cd còn biến chưa biết hay lệnh lồng,
# lệnh đổi thư mục không ở dạng cd đơn đầu đoạn, đích mở bằng `+` (xoay ngăn xếp pushd).
call("cy1", 'cd /tmp/x && cd "$(git rev-parse --show-toplevel)" && rm -rf src')
call("cy2", "cd /tmp/x && cd $OLDPWD && rm -rf src")
call("cy3", 'cd /tmp/x && cd "$REPO" && rm -rf src')
call("cy4", 'cd /tmp/x && cd "`git rev-parse --show-toplevel`" && rm -rf src')
call("cy5", "cd /tmp/x && builtin cd .. && rm -rf src")
call("cy6", "cd /tmp/x && time cd / && rm -rf home")
call("cy7", "cd /tmp/x && FOO=1 cd / && rm -rf home")
call("cy8", "cd /tmp/x && command cd / && rm -rf home")
call("cy9", "cd /tmp/x && source ./env.sh && rm -rf src")
call("cy10", "cd /tmp/x && . ./env.sh && rm -rf src")
call("cy11", "pushd /tmp/x && pushd +1 && rm -rf src")
# Tên lệnh đổi thư mục có nháy hay `\` vẫn là lệnh đó sau khi bash bỏ nháy: rm chạy ở /home/p (`.` thì ở nơi env.sh cd tới).
call("ce1", 'cd /tmp/x && "cd" /home/p && rm -rf src')
call("ce2", "cd /tmp/x && 'cd' /home/p && rm -rf src")
call("ce3", 'cd /tmp/x && c"d" /home/p && rm -rf src')
call("ce4", "cd /tmp/x && c\\d /home/p && rm -rf src")
call("ce5", "cd /tmp/x && $'cd' /home/p && rm -rf src")
call("ce6", 'cd /tmp/x && "." ./env.sh && rm -rf src')
call("ce7", "cd /tmp/x && chdir /home/p && rm -rf src")                  # zsh: chdir là builtin như cd
# `&` đơn chạy nền cả danh sách trước nó (`cd /tmp/x && true`) ở shell con: lệnh sau `&` chạy ở thư mục cũ.
call("ce8", "cd /tmp/x && true & rm -rf src")                            # bash xoá ./src của dự án
call("ce9", "cd /tmp/x && rm -rf y &")                                   # vô hại: cả danh sách chạy nền, rm ở /tmp/x
# Thân heredoc đưa vào shell chạy ở shell con: biến gán trong thân không ra ngoài, biến không export của shell cha rỗng trong
# thân <<'EOF' (<<EOF thì shell cha thay trước), chỉ shell cục bộ trơn chạy thân ở thư mục cd, thân chạy trước lệnh sau shell
# trên dòng mở. `\` cuối dòng mở kéo dòng kế (`| bash`) vào lệnh. Shell trơn không có heredoc không đọc dòng sau.
call("hd1", "bash <<'EOF'\nD=/tmp/x\nEOF\nrm -rf $D/src")               # D rỗng sau heredoc: bash xoá /src
call("hd2", "bash <<'EOF'\nD=/tmp/x\n# don't\nEOF\necho 'ok'; rm -rf $D/src")  # nháy lẻ trong thân không che dấu đóng
call("hd3", "cat <<'EOF' \\\n| bash\nrm -rf src\nEOF")
call("hd4", "cd /tmp/w && bash\nrm -rf src")                            # cd lỗi thì rm vẫn chạy ở dự án
call("hd5", "bash <<'EOF' && cd /tmp/x\nrm -rf src\nEOF")               # thân chạy trước cd
call("hd6", "bash <<'EOF'; D=/tmp/x\nrm -rf $D/src\nEOF")               # thân chạy trước khi gán D
call("hd7", "cd /tmp/w && bash <<'EOF'\nrm -rf y\nEOF\necho ok")        # vô hại: thân thừa hưởng thư mục cd
call("hd8", "cd /tmp/x && env -C / bash <<'EOF'\nrm -rf home\nEOF")     # thân chạy ở /: chỉ shell cục bộ trơn mới thừa hưởng
call("hd9", "cd /tmp/x && ssh host bash <<'EOF'\nrm -rf src\nEOF")      # thân chạy ở máy khác
call("hd10", "D=/tmp/x; bash <<'EOF'\nrm -rf $D/src\nEOF")              # shell con không thấy D (không export): xoá /src
call("hd11", "D=/srv/; cd /tmp/x && bash <<EOF\nrm -rf ${D}y\nEOF")     # <<EOF: shell cha thay D trước, bash xoá /srv/y
call("hd12", "export D=/srv/; cd /tmp/x && bash <<'EOF'\nrm -rf ${D}y\nEOF")  # D đã export: shell con thấy D, xoá /srv/y
# Biến chỉ gán trong thân là rỗng sau thân (không phải "không biết"); export hay không thì không đoán: đọc cả theo cách cũ
# (thân không phạm vi) rồi lấy hợp. Thân chỉ thừa hưởng thư mục khi shell nhận thân là lệnh cuối dòng mở. `cd -` dù có nháy.
call("hz1", "bash <<'EOF'\nD=/home/u\nEOF\ncd /tmp/x && rm -rf $D/src")      # D rỗng sau thân: bash xoá /src
call("hz2", "bash <<'EOF'\nD=/tmp/y\nEOF\ncd /tmp/x && rm -rf $D/src")      # D rỗng, không phải /tmp/y: bash xoá /src
call("hz3", "D=/srv/app/ bash <<'EOF'\ncd /tmp/x && rm -rf ${D}src\nEOF")  # gán tạm cho bash: thân thấy D, xoá /srv/app/src
call("hz4", "env D=/srv/app/ bash <<'EOF'\ncd /tmp/x && rm -rf ${D}src\nEOF")
call("hz5", "set -e -a; D=/srv/app/; cd /tmp/x && bash <<'EOF'\nrm -rf ${D}src\nEOF")  # set -a export D
call("hz6", "HOME=/home/u/; cd /tmp/x && bash <<'EOF'\nrm -rf ${HOME}proj\nEOF")       # HOME vốn đã export
call("hz7", "D=/srv/app/; bash <<'EOF'\nEOF\ncd /tmp/x && rm -rf ${D}src")  # thân rỗng: dòng sau EOF ở shell cha
call("hz8", "D=/srv/app/; bash <<'EOF' && cd /tmp/x && bash\nrm -rf ${D}src\nEOF")  # bash đầu nhận thân, ở dự án
call("hz9", "cat <<'EOF' \\\n| bash\nEOF\ncd /tmp/x && rm -rf $D/src")     # D chưa gán: bash xoá /src
call("hz10", "bash <<'EOF' && cd /tmp/x && bash\nrm -rf src\nEOF")         # thân chạy ở dự án, trước cd
call("hz11", "cd /tmp/x && cd \"-\" && rm -rf src")                          # về lại thư mục dự án
call("hz12", "cd /tmp/x && cd '-' && rm -rf src")
call("hz13", "cd /tmp/x || rm -rf src")                                      # rm chỉ chạy khi cd lỗi
call("hz14", "cd /tmp/x | rm -rf src")                                       # cd ở shell con của ống
call("hz15", "D=/tmp/y/; bash <<'EOF'\necho hi\nEOF\nrm -rf ${D}src")        # vô hại: D có từ trước thân, giữ /tmp/y/
# <<EOF không nháy: shell cha thay biến trong thân bằng giá trị của chính nó trước khi shell con chạy, nên biến gán trong thân
# không đổi phép thay đó. `\$` thoát thì shell con mới thay, khi đó thấy biến gán trong thân.
call("hv1", "bash <<EOF\nD=/tmp/x\nrm -rf $D/src\nEOF")                     # D rỗng ở shell cha: bash xoá /src
call("hv2", "D=/srv/; bash <<EOF\nD=/tmp/x/\nrm -rf ${D}src\nEOF")          # shell cha thay D=/srv/: xoá /srv/src
call("hv3", "cd /tmp/x && bash <<EOF\nD=/tmp/y\nrm -rf $D/src\nEOF")        # D rỗng: xoá /src (chạy ở /tmp/x)
call("hv4", "D=/tmp/x/; bash <<EOF\nD=/srv/\nrm -rf \\${D}src\nEOF")        # `\$`: shell con thay, xoá /srv/src
call("hv5", "D=/tmp/y/; bash <<EOF\nrm -rf ${D}src\nEOF")                   # bash xoá /tmp/y/src, audit báo thừa (s86–s91)
# Thân <<'EOF' chỉ được đưa vào bash nhờ `\` cuối dòng mở kéo `| bash`: biến đã export của shell cha vẫn thấy trong thân.
call("hv6", "export D=/srv/; cat <<'EOF' \\\n| bash\ncd /tmp/x && rm -rf ${D}src\nEOF")  # xoá /srv/src (chạy ở /tmp/x)
call("hv7", "export D=/srv/; cat <<'EOF' \\\n| bash\nrm -rf ${D}src\nEOF")               # xoá /srv/src
# PowerShell cũng đọc thêm thân heredoc theo cách cũ rồi lấy hợp; byte \x01–\x04 có sẵn trong lệnh không phải dấu ở cách
# đọc cũ. Guard không hỏi cả hai lệnh: vào A, không vào H.
call("hp1", "wsl bash -c 'export D=/srv/app/; cd /tmp/x && bash <<\"EOF\"\nrm -rf ${D}src\nEOF'", tool="PowerShell")  # xoá /srv/app/src
call("hp2", "D=/srv/a; echo '\x03'; rm -rf ${D}tmp/x")                        # bash xoá /srv/atmp/x
# Thân heredoc rỗng: dòng ngay sau dòng mở là dấu đóng, lệnh sau đó chạy ở shell cha. Chưa đóng thì thân tới hết chuỗi.
call("ha1", "cat > f <<'EOF'\nEOF\nrm -rf src")                               # bash xoá src ở thư mục dự án
call("ha2", "cat > f <<EOF\nEOF\nrm -rf src")
call("ha3", "cat > f <<-EOF\n\tEOF\nrm -rf src")                              # <<- bỏ tab đầu dòng đóng
call("ha4", "cat > f <<'EOF'\nEOF\nrm -rf src\nEOF")                          # EOF đầu đã đóng thân: bash xoá src
call("ha5", "bash <<'EOF'\nEOF\nrm -rf src")                                  # bash nhận thân rỗng, rm chạy ở shell cha
call("ha6", "cd /tmp/x && bash <<'EOF'\nEOF\nrm -rf src")                     # rm sau xuống dòng: cd lỗi thì xoá src của dự án
call("ha7", "bash <<'EOF'\nrm -rf src")                                       # chưa đóng, thân đưa vào bash: bash xoá src
# Dòng đầu chỉ đóng thân khi đúng là dấu đóng: `<<EOF` không bỏ tab, `\tEOF` là lệnh của thân, EOF sau mới đóng.
call("ha8", "bash <<EOF\n\tEOF\ncat > f <<'X'\nEOF\nrm -rf src\nX")             # bash xoá src
# `#` đầu từ ngoài nháy mở comment tới hết dòng: nháy trong comment không mở chuỗi, dòng sau vẫn là lệnh.
call("hb1", "# don't\nrm -rf src\necho 'x'")                                # bash xoá src ở thư mục dự án
call("hb2", "cd /tmp/x # don't\nrm -rf src\necho 'ok'")                     # rm sau xuống dòng: cd lỗi thì xoá src của dự án
call("hb3", "echo a \\\\\n# don't\nrm -rf src\necho 'x'")                   # `\\` là một `\` thường: `#` ở đầu dòng mới
# Cách che nháy cũ (không biết comment) vẫn trong hợp, kể cả ở cách đọc kéo dòng: chỉ nó báo ca này, nhờ `#'` ghép với
# nháy của dòng được `\` kéo vào làm `$x` lọt vào đích.
call("hb4", "true | cd /tmp/x && rm -rf y #'\ncat <<'EOF' \\\n# don't $x\nEOF")  # cd ở shell con của ống: bash xoá ./y
# Byte \x01–\x04 có sẵn trong lệnh là chữ thường với bash, không phải dấu đóng/mở thân của cách đọc scoped.
call("hb5", "D=/tmp/y/; bash <<'EOF'\n\x01\nrm -rf ${D}src\nEOF")             # D không export: bash xoá ./src
call("hb6", "bash <<'EOF'\nD=/tmp/x/\n\x02\nEOF\nrm -rf ${D}src")             # D chỉ gán trong thân: bash xoá ./src
# Shell cha thay biến trong thân <<EOF ngay tại toán tử heredoc: trước lệnh sau toán tử trên dòng mở, không thấy gán tạm
# trước lệnh. Thân <<'EOF' thì shell con thay, thấy gán tạm của chính nó.
call("hb7", "bash <<EOF; D=/tmp/x\nrm -rf $D/src\nEOF")                         # D chưa gán khi thay: bash xoá /src
call("hb8", "bash <<EOF && D=/tmp/x\nrm -rf $D/src\nEOF")                       # bash xoá /src
call("hb9", "D=/tmp/x/ bash <<EOF\nrm -rf ${D}src\nEOF")                        # bash xoá ./src
call("hb10", "D=/srv/x/ bash <<'EOF'\nrm -rf ${D}src\nEOF")                     # bash xoá /srv/x/src
# Byte \x01–\x04 có sẵn là chữ với bash, nhưng cách đọc coi chúng là dấu (như 695e799) vẫn trong phép hợp: nó báo được các
# lệnh này nhờ byte giả xoá env, gốc lỗi ở chỗ khác. Bash chạy cả ba với $D rỗng: xoá /src.
call("hf1", "\x01\ncd /tmp/x # don't\ncd proj; D=/tmp/x/ \\\\\n\x03\ncd /tmp/x # don't\nrm -rf $D/src")  # `\\`: D gán tạm cho lệnh `\`
call("hf2", "'\necho 'a b'\n\x02\n#'\necho ${#x} | D=/tmp/x/ # x \\\nrm -rf $D/src; echo \\#z \\",
     tool="PowerShell")                       # chỉ bản PowerShell mất nhãn; với bash, D gán ở shell con của ống
call("hf3", "bash <<'EOF'\nbash <<EOF; D=/tmp/x\n\x03\n(rm -rf $D/src)")       # thân <<EOF lồng được thay trước khi gán D
# cd ngay sau `||` hay `|` không đặt thư mục cho lệnh sau `&&`: `(true || cd x) && rm` bỏ qua cd, cd trong ống chạy ở shell con.
call("hf4", "true || cd /tmp/x && rm -rf y")                                  # bash xoá ./y ở thư mục dự án
call("hf5", "true | cd /tmp/x && rm -rf y")                                   # bash xoá ./y ở thư mục dự án
# Gán tạm trước lệnh khác và `NAME=VALUE` là tham số của lệnh khác không đổi biến của shell: chỉ đoạn toàn phép gán, hay tham
# số của export/declare/typeset/local/readonly mới đổi.
call("hf6", "D=/tmp/x/ true; rm -rf ${D}src")                                # D chỉ có trong env của true: bash xoá ./src
call("hf7", "echo D=/tmp/x/; rm -rf ${D}src")                                # D=/tmp/x/ là tham số của echo: bash xoá ./src
call("hf8", "env D=/tmp/x/ true; rm -rf ${D}src")                            # bash xoá ./src
call("hf9", "true;D=/tmp/x/ true;rm -rf ${D}src")                            # bash xoá ./src (`;D=` không có khoảng trắng)
call("hf10", "D=/tmp/x/; rm -rf ${D}src")                                    # vô hại: bash xoá /tmp/x/src
call("hf11", "export D=/tmp/x/; rm -rf ${D}src")                             # vô hại: bash xoá /tmp/x/src
# `\` lẻ cuối dòng mở heredoc nối dòng EOF ngay sau vào lệnh (thành tham số), không phải dấu đóng thân rỗng: thân là các dòng
# sau đó tới EOF kế.
call("hg1", "D=/tmp/x/; bash -s <<'EOF' \\\nEOF\nrm -rf ${D}src\nEOF")   # D không export: bash xoá ./src
call("hg2", "D=/tmp/x/; sh <<'EOF' -s \\\nEOF\nrm -rf ${D}src\nEOF")     # bash xoá ./src
call("hg3", "bash -s <<EOF \\\nEOF\nD=/tmp/x/\nrm -rf ${D}src\nEOF")      # shell cha thay ${D} rỗng trước: bash xoá ./src
call("hg4", "cat > f <<'EOF' \\\\\nEOF\nrm -rf src")                       # `\\` là một `\` thường: thân rỗng, bash xoá ./src
# Cách đọc scoped với heredoc như 6f32d5a (không nhận thân rỗng) vẫn ở trong phép hợp khi hai cách đọc heredoc khác nhau.
# hg5, hg6 nay còn được cách đọc strict_assign (b377b11) phủ: bỏ cách đọc empty_body=False vẫn báo cả hai. hh1, hh2 canh nó.
call("hg5", "false && D=/tmp/x/\nbash <<'EOF'\nEOF\nrm -rf ${D}src")      # D không được gán: bash xoá ./src
call("hg6", "D=/tmp/x/ | true\nbash <<'EOF'\nEOF\nrm -rf ${D}src\nEOF")  # D gán ở shell con của ống: bash xoá ./src
# Phép gán sau `&&`, `||` có thể không chạy; trong ống (`|` trước hay sau) hay chạy nền (`&`) thì chạy ở shell con: không đổi
# biến của shell.
call("hg7", "false && D=/tmp/x/; rm -rf ${D}src")                         # gán không chạy: bash xoá ./src
call("hg8", "true || D=/tmp/x/; rm -rf ${D}src")                          # gán không chạy: bash xoá ./src
call("hg9", "D=/tmp/x/ | true; rm -rf ${D}src")                           # gán ở shell con của ống: bash xoá ./src
call("hg10", "true | D=/tmp/x/; rm -rf ${D}src")                          # bash xoá ./src
call("hg11", "D=/tmp/x/&\nrm -rf ${D}src")                                # gán ở shell con chạy nền: bash xoá ./src
call("hg12", "export D=/tmp/x/ &\nrm -rf ${D}src")                        # bash xoá ./src
# Escape ANSI-C trong `$'…'` cho ra tên lệnh bất kỳ: `$'\x63d'` là cd.
call("hg13", "cd /tmp/x && $'\\x63d' /home/p && rm -rf src")              # bash xoá src ở /home/p
# Hai heredoc trên một dòng: thân <<'A' rỗng, thân <<'EOF' đưa vào bash. Audit chỉ xét toán tử đầu: cách đọc nhận thân rỗng
# để rm ở shell cha (D=/tmp/x/), chỉ cách đọc như 6f32d5a (empty_body=False) đưa rm vào thân, nơi D không export là rỗng.
call("hh1", "D=/tmp/x/; bash <<'A' <<'EOF'\nA\nrm -rf ${D}src\nEOF")      # bash xoá ./src
call("hh2", "D=/tmp/x/; bash <<'A' <<'EOF'\nA\nrm -rf ${D}src\nEOF\nA")   # bash xoá ./src (dòng A cuối: command not found)
# Phép gán sau `&&` chạy khi lệnh trước thành công: cách đọc gán chặt (strict_assign) bỏ qua nó nên thấy D=/tmp/x/, chỉ cách
# đọc gán lỏng như f5bc021 (strict_assign=False) thấy D=/srv/.
call("hi1", "D=/tmp/x/; true && D=/srv/; rm -rf ${D}src")                 # true thành công nên gán chạy: bash xoá /srv/src
# Comment sau `||`/`|` không phải dấu ngắt: cd ở dòng sau vẫn là vế phải của `||` hay chạy trong ống; `;`, `&&`, `|` trong
# comment cũng không ngắt (blissful-dirac 8fbb100, efa2ed3). Bash 5.2: rm chạy ở thư mục dự án.
call("s38", "true || # x\ncd /tmp/w && rm -rf src")
call("s39", "true | # x\ncd /tmp && rm -rf src")
call("s40", "true || # a ; b\ncd /tmp/w && rm -rf src")
call("s41", "true || # a && b\ncd /tmp/w && rm -rf src")
call("s42", "true | # a | b\ncd /tmp && rm -rf src")
# Phép gán trong phần chạy nền (`&` chạy cả danh sách hay cả nhóm `{ …; }` ở shell con) hay trong subshell `( … )` không đổi
# biến của shell cha (blissful-dirac 9734b56; ca cuối từ oracle bash của nhánh đó). Bash 5.2: rm xoá /src hay ./src.
call("s59", "{ D=/tmp/x; } &\nrm -rf $D/src\nwait")
call("s60", "D=/tmp/x && true &\nrm -rf $D/src\nwait")
call("s61", "D=/tmp/x && true & true; rm -rf $D/src\nwait")
call("s62", "D=src; { D=/tmp/x; } &\nrm -rf $D\nwait")
call("sb1", "cd /tmp/khongco src; D=/tmp/w || cd /tmp/w & true; rm -rf $D/src\nwait")
call("sb2", "( D=/tmp/x; ); rm -rf $D/src")
call("sb3", "D=/tmp/x; { true; } &\nrm -rf $D/src\nwait")                 # vô hại: D gán ở shell cha
# `\$` trong thân `<<EOF` không nháy là `$` chữ: shell cha không thay, shell con thay bằng env của nó, nơi D không export
# là rỗng (blissful-dirac 9734b56). Bash 5.2: rm xoá /src.
call("s65", "D=/tmp/x; bash <<EOF\nrm -rf \\$D/src\nEOF")
# Shell cha thay thân `<<EOF` bằng biến của nó lúc chạy lệnh mở: chỉ tin biến mà phép gán chắc đã chạy (blissful-dirac
# 5f2f9c2): sau `if false`, trong thân dữ liệu audit đọc lệch (`<<\EOF`, dòng ` EOF`), trong nháy ở chế độ `| bash`, biến bị
# unset, declare -u, cd đổi PWD, `$[D=5]` trong lệnh mở, biến bash tự đặt (RANDOM, `_`). Bash 5.2: rm xoá /src hay src.
call("s74", "if false; then\nD=/tmp/x\nfi\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s75", "cat <<\\EOF\nD=/tmp/x\nEOF\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s76", "cat <<EOF >/dev/null\nx\n EOF\nD=/tmp/x\nEOF\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s78", "echo 'a;D=/tmp/x;b'; cat <<EOF | bash\nrm -rf $D/src\nEOF")
call("s79", "D=/tmp/x; unset D; bash <<EOF\nrm -rf $D/src\nEOF")
call("s80", "declare -u D; D=/tmp/x; bash <<EOF\nrm -rf $D/src\nEOF")
call("s81", "PWD=/tmp/x; cd src; bash <<EOF\nrm -rf $PWD\nEOF")
call("s82", "D=/tmp/x; bash -s $[D=5] <<EOF\nrm -rf $D/src\nEOF")
call("s84", "RANDOM=/tmp/x; bash <<EOF\nrm -rf $RANDOM/src\nEOF")
call("s85", "_=/tmp/x; bash <<EOF\nrm -rf $_/src\nEOF")
call("sc1", "D=/tmp/x; bash <<EOF\nrm -rf $D/src\nEOF")                     # bash xoá /tmp/x/src, audit báo thừa (s86–s91)
# Audit không đoán biến của shell cha trong thân `<<EOF` không nháy (blissful-dirac cd828ea): vòng lặp thế lại thân mỗi lần
# chạy, bash lấy cả từ `EOF.x`, `EOF-1`, `EOF\r` làm delimiter (audit chỉ đọc `EOF`), shell con brace-expand giá trị đã thế.
# Bash 5.2: rm xoá /src hay /x/src.
call("s86", "D=/tmp/x\nwhile bash <<EOF\nrm -rf $D/src\ntest -n \"$D\"\nEOF\ndo unset D\ndone")
call("s87", "D=/tmp/x\nbash <<EOF.x\ntrue\nEOF.x\nunset D\nrm -rf $D/src")
call("s88", "D=/tmp/x\nbash <<EOF-1\nEOF-1\nD=\nrm -rf $D/src")
call("s89", "D=/tmp/x\nbash <<EOF\r\ntrue\nEOF\r\nunset D\nrm -rf $D/src")
call("s90", "D={/tmp/,/}x\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s91", "D=/tmp/x,/\nbash <<EOF\nrm -rf {$D}/src\nEOF")
# Các lệnh khác của blissful-dirac mà nền (mặc định + PR #5) bỏ sót, nay bắt được nhờ các bản port youthful-fermi tương
# ứng (thân rỗng, đích còn biến, cd sau `||`/`|`/trước `&`, biến trong thân <<EOF, gán tạm/sau &&/trong ống). Bash 5.2: rm
# chạy ở thư mục dự án hay xoá /src.
call("s16", "cat <<'EOF'\nEOF\nrm -rf src")
call("s21", "cd /tmp && rm -rf $D")
call("s23", "true | cd /tmp && rm -rf src")
call("s26", "( D=/tmp/x ); rm -rf $D/src")
call("s30", "true || cd /tmp/w && rm -rf src")
call("s31", "test -d /tmp/w || cd /tmp/w && rm -rf src")
call("s32", "cd src || cd /tmp/w && rm -rf build2")
call("s33", "cd /tmp/w && true & rm -rf src")
call("s34", "cd /tmp/w && rm -rf a & rm -rf src")
call("s56", "bash <<EOF\nD=/tmp/x; rm -rf $D/src\nEOF")
call("s57", "cat <<EOF | bash\nexport D=/tmp/x\nrm -rf $D/src\nEOF")
call("s58", "D=src; bash <<EOF\nD=/tmp/x; rm -rf $D\nEOF")
call("s63", "bash <<EOF; D=dist\nrm -rf $D/src\nEOF")
call("s64", "bash <<EOF && cd dist\nD=/tmp/x; rm -rf $D/src\nEOF")
call("s66", "D=/tmp/x bash <<EOF\nrm -rf $D/src\nEOF")
call("s67", "D=/tmp/x cat <<EOF | bash\nrm -rf $D/src\nEOF")
call("s68", "false && D=/tmp/x\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s69", "true || D=/tmp/x\ncat <<EOF | bash\nrm -rf $D/src\nEOF")
call("s70", "D=src | D=/tmp/x\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s71", "echo D=/tmp/x; cat <<EOF | bash\nrm -rf $D/src\nEOF")
call("s72", "true # D=/tmp/x\nbash <<EOF\nrm -rf $D/src\nEOF")
call("s73", 'echo " D=/tmp/x"; bash <<EOF\nrm -rf $D/src\nEOF')
call("s77", "true # it's\necho 'a; D=/tmp/x; b'; bash <<EOF\nrm -rf $D/src\nEOF")
call("s83", "bash <<EOF;D=dist\nrm -rf $D/src\nEOF")
# Biến audit không thay được (không gán trong lệnh, gán trong subshell) có thể chứa `..`, khoảng trắng (tách thành đích khác)
# hay đường tuyệt đối, dù nằm sau thư mục tạm hay tên lành (blissful-dirac 749e0c6). Bash 5.2 với biến kế thừa rỗng: s92 xoá
# /tmp/; s93, s94 vô hại (báo thừa có chủ ý: biến kế thừa có thể là `..`).
call("s92", "rm -rf /tmp/$X")
call("s93", "cd /tmp && rm -rf node_modules/$X")
call("s94", "(D=..); rm -rf node_modules/$D")
# Port blissful-dirac (98b74d0, fixture s101–s137) và ca P3 của docs/viec-can-lam.md: biến chỉ đổi theo phép gán thuần chắc
# chạy ở shell này. Chữ NAME=… là đối số của lệnh khác, gán tạm, gán trong ống, sau `&&`/`||`, trong lệnh ghép hay thân hàm,
# `local` ngoài hàm, gán rỗng, unset: bash 5.2 xoá ngoài thư mục tạm ở mọi lệnh dưới đây trừ s106–s108, s112, s113,
# s122–s125, s133–s136 (xoá trong /tmp/x).
call("s101", "true D=dist; rm -rf $D/src")
call("s102", "make PREFIX=/tmp/x install; rm -rf $PREFIX/lib")
call("s103", "D=/tmp/x true; rm -rf $D/src")
call("s104", "D=/tmp/x | true; rm -rf $D/src")
call("s105", "echo D=/tmp/x; rm -rf $D")
call("s106", "D=/tmp/x; rm -rf $D/src")
call("s107", "export D=/tmp/x; rm -rf $D/src")
call("s108", "D=/tmp/x E=/tmp/y; rm -rf $D $E")
call("s109", "D=/tmp/x; { D=..; }; true D=/tmp/x; rm -rf node_modules/$D")
call("s110", "D=/tmp/x; D=.. # c\ntrue D=/tmp/x; rm -rf node_modules/$D")
call("s111", "echo a\\|#b | # c\nexport D=/tmp/x; rm -rf $D/src")
call("s112", "true # a |\nD=/tmp/x\nrm -rf $D/src")
call("s113", "D=/tmp/x # c | d\nrm -rf $D/src")
call("s114", "local D=/tmp/x; rm -rf $D/src")
call("s115", "D=/tmp/x; D=; rm -rf $D/src")
call("s116", 'D=/tmp/x; D=""; rm -rf $D/src')
call("s117", "D=/tmp/x; unset D; rm -rf $D/src")
call("s118", "D=/tmp/x; D= E=/tmp/y; rm -rf $D/src")
call("s119", "D=/tmp/x; export D=; rm -rf $D/src")
call("s120", "D=/tmp/x; { unset -v D; }; rm -rf $D/src")
call("s121", "f() { true; D=/tmp/w; local D=..; true D=/tmp/y; rm -rf node_modules/$D; }; f")
call("s122", "D=/tmp/x; export D; rm -rf $D/src")
call("s123", "D=/tmp/x; unset -f D; rm -rf $D/src")
call("s124", "D=/tmp/x; unset D | true; rm -rf $D/src")
call("s125", "D=/tmp/x; D= true; rm -rf $D/src")
call("s126", "D=..; if false; then D=; fi; true D=/tmp/y; rm -rf node_modules/$D")
call("s127", "D=..; f() { true; D=; }; true D=/tmp/y; rm -rf node_modules/$D")
call("s128", "if false; then D=/tmp/z; fi; rm -rf $D/src")
call("s129", "false && D=/tmp/x; rm -rf $D/src")
call("s130", "while false; do D=/tmp/x; done; rm -rf $D/src")
call("s131", "if true; then echo a\\; fi; else D=/tmp/x; fi; rm -rf $D/src")
call("s132", "if false; then x=$(if true; then echo; fi); D=/tmp/x; fi; rm -rf $D/src")
call("s133", "if true; then :; fi; D=/tmp/x; rm -rf $D/src")
call("s134", "f() { :; }; D=/tmp/x; rm -rf $D/src")
call("s135", "x=$(for i in 1; do echo; done); D=/tmp/x; rm -rf $D/src")
call("s136", "D=/tmp/x && rm -rf $D/src")
call("s137", "D=/tmp/x; function f { D=..; }; f; true D=/tmp/y; rm -rf node_modules/$D")
# Ca thêm của P3 và 2.2, ca ngắn nhất oracle bash (lô var_trap2) tìm ra trên nền: bash 5.2 xoá /, /etc, node_modules/../..
# hay dist/../.. (thư mục cha của dự án). s143: `D="x /"` trong thân đưa vào shell qua ống (nháy không được che) và
# `D=/tmp/w &` chạy nền không đổi D: rm xoá /tmp/w/x và /.
call("s138", 'D=/tmp/w; read -aD <<< /etc; rm -rf "$D"')
call("s139", "D=/tmp/w; unset D -f; rm -rf $D/a")
call("s140", "D=../.. # a\n{ D=~; } | true && rm -rf node_modules/$D")
call("s141", "D=../..; local D=/tmp/w; rm -rf node_modules/$D")
call("s142", "export D=../..; { D=/tmp/w; } | true | rm -rf dist/$D")
call("s143", "cat <<'EOF' | bash\nD=~; D=\"x /\"; D=/tmp/w & true; rm -rf /tmp/w/$D\nEOF")
# Reviewer của cách đọc pure: comment chen sau `&&`, `)` của mẫu case trong subshell, gọi hàm qua biến, hàm tên export
# (bash 5.2 xoá //src ở cả năm lệnh).
call("s144", "D=/; false && # c\nD=/tmp/x; rm -rf $D/src")
call("s145", "D=/; false &&\n\n# c\n\nD=/tmp/x\nrm -rf $D/src")
call("s146", "D=/; ( case a in a) :;; esac; D=/tmp/x; ); rm -rf $D/src")
call("s147", "f() { D=/; }; D=/tmp/x; F=f; $F; rm -rf $D/src")
call("s148", "export() { D=/; }; D=/tmp/w; export D=/tmp/x; rm -rf $D/src")
# P2: here-string đưa vào shell: bash chạy chuỗi như lệnh (bash 5.2 xoá ./src, /tmp/w/.. tức /tmp, ./src).
call("s149", "bash <<< 'rm -rf src'")
call("s150", "D=/tmp/w; sh <<< \"rm -rf $D/..\"")
call("s151", "cat <<< 'rm -rf src' | bash")
# Reviewer của cách đọc bash: `\$D` trong here-string nháy kép để shell con thay (bash xoá //src); `<<<` trong comment hay
# trong nháy không mở here-string, nháy lẻ sau nó không nuốt lệnh sau (bash xoá /a).
call("s152", "D=/tmp/w; bash <<< \"D=/; rm -rf \\$D/src\"")
call("s153", "# bash <<< '\ncat <<'E-X'\nD=/tmp/w\nE-X\nrm -rf $D/a\n# '")
call("s154", "echo \"bash <<< '\"; cat <<'E-X'\nD=/tmp/w\nE-X\nrm -rf $D/a\necho \"'\"")
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

# Bộ lệnh dùng chung của assert phải nghi và bước so nhãn với bản trước, chép từ nhánh vibrant-pascal (970114a, lệnh và
# lý do nguyên văn): MISSED_VP, fuzz_vp_b(), fuzz_vp_c() (mỗi hàm một bộ sinh riêng). Nạp bằng đường dẫn file.
vp="$tmp/missed_vp.py"
cat > "$vp" <<'PYEOF'
import random

# Lệnh bash thực sự xoá đích nguy hiểm mà mục A từng bỏ sót (oracle bash của nhánh vibrant-pascal tìm ra), kèm lý do:
# mục A phải nghi.
MISSED_VP = [
    ("echo it\\'s\nrm -rf src 'x'", "`\\'` ngoài nháy là chữ `'`, không mở chuỗi ghép với nháy sau: rm ở dòng sau xoá src và x của dự án"),
    ("D=/; bash <<EOF\nD=/tmp/w && rm -rf $D/a\nEOF", "thân `<<EOF` không nháy được shell cha thay `$D` (= /) trước khi shell con gán: xoá /a"),
    ("D=/tmp/w; read D <<< /; rm -rf \"$D\"", "read gán lại D = /: xoá /"),
    ("D=/tmp/w; eval 'D=/'; rm -rf \"$D\"", "eval gán lại D = /: xoá /"),
    ("D=/tmp/w; printf -v D /; rm -rf \"$D\"", "printf -v gán lại D = /: xoá /"),
    ("D=/tmp/w; unset D; rm -rf $D/a", "unset bỏ D: xoá /a"),
    ("cat <<'EOF'\nEOF\nrm -rf src", "heredoc thân rỗng đóng ngay ở dòng EOF: rm sau đó là lệnh thật, xoá src của dự án"),
    *((c, "`<<<` là here-string, không mở heredoc: rm ở dòng sau là lệnh thật, xoá src của dự án")
      for c in ("read D <<< x\nrm -rf src", "cat <<< EOF\nrm -rf src\nEOF")),
    ("cd /tmp && rm -rf $D/a", "D chưa gán: `$D/a` là /a, đường tuyệt đối không nằm trong thư mục cd"),
    ("echo D=/tmp/w; rm -rf $D/a", "`D=/tmp/w` là tham số của echo, không phải phép gán: D rỗng, xoá /a"),
    ("D=/tmp/w true; rm -rf $D/a", "gán tạm trước lệnh chỉ áp cho lệnh đó: D rỗng khi rm chạy, xoá /a"),
    ("false && D=/tmp/w; rm -rf $D/a", "false nên phép gán sau `&&` không chạy: D rỗng, xoá /a"),
    ("export D=/tmp/w | rm -rf ${D}src", "mỗi khâu của ống chạy ở shell con: D không sang khâu rm, xoá src của dự án"),
    ("D=/tmp/w || cd /tmp/w && rm -rf src", "phép gán thành công nên cd sau `||` bị bỏ qua: rm xoá src của dự án"),
    ("echo | cd /tmp/w && rm -rf src", "cd trong ống chạy ở shell con, không đổi thư mục: rm xoá src của dự án"),
    ("cd /tmp && rm -rf {a,/}", "brace mở thành `a /`: xoá cả /"),
    *((c, "cờ trước -c (cờ dài, cờ có tham số, cụm cờ ngắn có chữ c): shell vẫn chạy rm -rf /") for c in (
        "bash --rcfile f -c 'rm -rf /'", "bash -o pipefail -c 'rm -rf /'", "bash +o pipefail -c 'rm -rf /'",
        "bash -O extglob -c 'rm -rf /'", "bash --norc -c 'rm -rf /'", "bash --init-file f -c 'rm -rf /'",
        "bash -lc 'rm -rf /'", "sh -ec 'rm -rf /'", "zsh -o errexit -c 'rm -rf /'")),
    *((c, "comment `#` mở từ tới hết dòng: nháy lẻ trong `# don't` không ghép với nháy sau, rm là lệnh thật, xoá src")
      for c in ("# don't\nrm -rf src 'x'", "echo x # don't\nrm -rf src 'x'")),
    ("echo $'it\\'s'\nrm -rf src 'x'", "`\\'` trong `$'…'` là chữ, chuỗi đóng ở nháy kế: rm ở dòng sau xoá src"),
    ("D=/tmp/w; (D=/; rm -rf ${D}src)", "phép gán ngay sau `(` có hiệu lực trong subshell: xoá /src"),
    ("(export D=/tmp/w/); rm -rf ${D}src", "phép gán trong subshell không ra ngoài: D rỗng, xoá src của dự án"),
    ("D=/tmp/w |& true; rm -rf $D/a", "`|&` cũng là ống: phép gán ở khâu shell con, D rỗng, xoá /a"),
    ("D=/; local D=/tmp/w; rm -rf $D/a", "local ngoài hàm là lỗi, D vẫn là /: xoá /a"),
    ("D=/tmp/w; mapfile -t D <<< /; rm -rf $D/a", "mapfile gán lại D = /: xoá //a"),
    ("D=/tmp/w; : ${D:=/}; unset D; : ${D:=/}; rm -rf $D/a", "`${D:=/}` gán D khi D rỗng: xoá //a"),
    ("D=/tmp/w; ((D=0)); rm -rf $D/a", "gán số học: D = 0, xoá 0/a của dự án"),
    ("X=/tmp/x; IFS=/; rm -rf $X", "IFS=/ tách $X thành `tmp` và `x` tương đối: xoá x của dự án"),
    ("D=/tmp/w; bash -c 'rm -rf $D/a'", "D không export: thân bash -c thấy D rỗng, xoá /a"),
    ("D=/tmp/w; bash <<\\EOF\nrm -rf $D/a\nEOF", "`<<\\EOF` là tên trong nháy: shell cha không thay, shell con thấy D rỗng, xoá /a"),
    ("cat <<-EOF\n\tEOF\nrm -rf src", "`<<-` bỏ tab đầu dòng đóng: thân rỗng, rm là lệnh thật, xoá src"),
    *((c, "shell cha chạy lệnh lồng trong thân heredoc dữ liệu không nháy: xoá src")
      for c in ("cat <<EOF\n$(rm -rf src)\nEOF", "cat <<EOF\n`rm -rf src`\nEOF")),
    ("true || cd /tmp/x && rm -rf src", "true thành công nên cd sau `||` bị bỏ qua: rm xoá src của dự án"),
    *((c, "đích còn biến chưa gán, hay `..` viết trong nháy hoặc sau `\\`: ra ngoài thư mục cd, xoá /home") for c in (
        "cd /tmp/x && rm -rf $D/home", "cd /tmp/x && rm -rf .'.'/.'.'/home", "cd /tmp/x && rm -rf .\\./.\\./home")),
    *((c, "tên heredoc là cả một từ shell (có `-`, `.`, nháy hay `\\` giữa từ), dòng đóng đúng bằng tên đã bỏ nháy: rm sau "
          "dòng đóng là lệnh thật, xoá src") for c in (
        "cat <<EOF-PY\nx\nEOF-PY\nrm -rf src", "cat <<END-X\nx\nEND-X\nrm -rf src", "cat <<EOF.\nx\nEOF.\nrm -rf src",
        "cat <<E\"O\"F\nhi\nEOF\nrm -rf src", "cat <<E\\OF\nhi\nEOF\nrm -rf src", "cat <<\"EOF\"x\nhi\nEOFx\nrm -rf src",
        "cat <<-EOF-PY\n\tx\n\tEOF-PY\nrm -rf src")),
    *((c, "tên heredoc có phần trong nháy hay sau `\\`: shell cha không thay biến trong thân, shell con thấy D (không "
          "export) rỗng, xoá /a") for c in (
        "D=/tmp/w; bash <<'E-X'\nrm -rf $D/a\nE-X", "D=/tmp/w; bash <<\"E.X\"\nrm -rf $D/a\nE.X",
        "D=/tmp/w; bash <<E\\X\nrm -rf $D/a\nEX")),
    ("D=/; bash <<E-X\nD=/tmp/w && rm -rf $D/a\nE-X", "thân `<<E-X` không nháy: shell cha thay `$D` (= /) trước khi shell con gán, xoá //a"),
    *((c, "tên heredoc bỏ nháy như bash (`$\"E\"` như `\"E\"`, `\\` + xuống dòng trong `\"…\"` bị bỏ; `$'…'` có `\\` được "
          "bash giải mã): heredoc đóng ở dòng có thật, unset D rồi rm xoá /a") for c in (
        'D=/tmp/w; cat <<$"E"\nx\nE\nunset D; rm -rf $D/a', "D=/tmp/w; cat <<$'E\\x41'\nx\nEA\nunset D; rm -rf $D/a",
        "D=/tmp/w; cat <<$'\\x45'\nx\nE\nunset D; rm -rf $D/a", 'D=/tmp/w; cat <<"E\\\nF"\nx\nEF\nunset D; rm -rf $D/a')),
    *((c, "`\\r` là chữ của từ (bash chỉ tách từ ở dấu cách, tab, xuống dòng): tên heredoc `E\\r` không đóng nên cả phần sau "
          "là thân không nháy, `$(rm -rf src)` chạy; `EOF\\r` đóng ở dòng `EOF\\r`, rm sau đó là lệnh thật: xoá src") for c in (
        "cat <<E\r\ncat <<'X'\n$(rm -rf src)\nX", "cat <<EOF\r\nx\r\nEOF\r\nrm -rf src")),
    *((c, "`\\` + xuống dòng trong tên heredoc là nối dòng như bash (`E\\`⏎`F` là EF, `\\`⏎`E` là E, không nháy): thân là "
          "dữ liệu (D gán trong thân không có hiệu lực), rm sau dòng đóng là lệnh thật, xoá src hay /a") for c in (
        "cat <<E\\\nF\nx\nEF\nrm -rf src", "cat <<E\\\nF\nD=/tmp/w\nEF\nrm -rf $D/a", "cat <<\\\nE\nD=/tmp/w\nE\nrm -rf $D/a",
        "cat <<E\\\nOF\nx\nEOF\nrm -rf src", "cat <<E\\\nOF\nD=/tmp/w\nEOF\nrm -rf $D/a")),
    ("cat <<1E\nD=/tmp/w\n1E\nrm -rf $D/a", "tên heredoc mở bằng chữ số vẫn là heredoc: `D=/tmp/w` là dữ liệu, D rỗng, xoá /a"),
    *((c, "`<<` trong `$((…))` là phép dịch bit, không mở heredoc: lệnh ở dòng sau là lệnh thật, xoá src hay /a") for c in (
        "echo $((x<<y))\nrm -rf src", "n=2; echo $((1<<n))\nrm -rf src", "echo $((1<<2))\nD=/tmp/w; unset D; rm -rf $D/a")),
    ("let 'x=1<<2'\ncat <<EOF\n$(rm -rf src)\nEOF\nlet 'y=1<<2'", "`<<` trong nháy không mở heredoc, nháy sau nó đóng chuỗi chứ "
     "không mở tên nhiều dòng: thân `<<EOF` không nháy, shell cha chạy `$(rm -rf src)`, xoá src"),
    *((c, "lệnh đổi biến viết trong nháy hay có `\\` vẫn là lệnh đó: D bị bỏ hay gán lại thành /, xoá /a hay /") for c in (
        "D=/tmp/w; 'unset' D; rm -rf $D/a", "D=/tmp/w; un''set D; rm -rf $D/a", "D=/tmp/w; \"read\" D <<< /; rm -rf \"$D\"",
        "D=/tmp/w; r\\ead D <<< /; rm -rf \"$D\"")),
    ("D=/tmp/w; D[0]=/; rm -rf $D/a", "gán phần tử 0 của mảng là gán chính D: D = /, xoá //a"),
    *((c, "tên biến dính liền cờ (`-vD`, `-aD`): printf, read vẫn gán lại D = /, xoá /")
      for c in ("D=/tmp/w; printf -vD /; rm -rf \"$D\"", "D=/tmp/w; read -aD <<< /; rm -rf \"$D\"")),
    *((c, "cd viết trong nháy hay có `\\` vẫn đổi thư mục: rm chạy ở dự án, xoá src") for c in (
        "cd /tmp/x && 'cd' /home/u/proj && rm -rf src", "cd /tmp/x && c\\d /home/u/proj && rm -rf src",
        "cd /tmp/x && 'pushd' /home/u/proj && rm -rf src")),
    *((c, "`((` trong nháy hay comment không mở số học (`\\` cuối comment là chữ, `\\\\` cuối dòng không nối dòng): "
          "`<<E-X` mở heredoc, thân là dữ liệu, rm sau dòng đóng là lệnh thật, xoá src hay /a") for c in (
        'echo "((" ; cat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a', "echo \"((\" ; cat <<E-X\ncat <<'Z'\nE-X\nrm -rf src",
        '[[ $x == "((" ]] && cat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a', '# ((\\\ncat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a',
        'echo "a\\\\" "(("\\\\\ncat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a')),
    *((c, "`<<` trong `$((…))`, `((…))`, `$[…]` là dịch bit (`))` trong nháy không đóng gì, số học kéo qua xuống "
          "dòng): không mở heredoc, lệnh sau là lệnh thật, D chỉ gán trong comment, xoá src hay /a") for c in (
        "# D=/tmp/w\necho '))'; echo $((1<<2))\nrm -rf $D/a", "# D=/tmp/w\necho '))'; ((x=1<<3))\nrm -rf $D/a",
        "# D=/tmp/w\necho $[1<<2]\nrm -rf $D/a", "echo $[1<<2]\ncat <<E-X\nx\nE-X\nrm -rf src",
        "x=$((1+\n2<<n))\nrm -rf src")),
    *((c, "`<<` trong nháy, comment hay sau `\\` không mở heredoc (nháy sau nó cũng không ghép thành tên): heredoc thật "
          "sau đó đóng ở dòng có tên, rm sau nó (hay trong thân đưa vào bash) là lệnh thật, xoá src hay /a") for c in (
        "let 'x=1<<2'; cat <<'E-X'\nD=/tmp/w\nE-X\nrm -rf $D/a", "# 1<<2\ncat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a",
        "echo x # a<<b\ncat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a", "echo \\<<E-X\nrm -rf src\nE-X",
        "let 'a=1<<2'; cat <<'E\nF' | bash\necho $((x<<y))\necho $((1<<2)); cat <<-'E\nF' | bash\nrm -rf src")),
    *((c, "tên heredoc `$'…'` được bash giải mã (`\\x45`, `\\105`, `\\u0045` là E): thân đưa vào sh chạy `cat <<E-X | bash` "
          "hay thân dữ liệu đóng ở dòng E, EA, rm là lệnh thật, xoá src hay /a") for c in (
        "sh <<$'\\x45' | bash\ncat <<E-X\nrm -rf src", "sh <<-$'\\x45' | bash\nlet 'a=1<<2'; cat <<E$X\nrm -rf src",
        "cat <<$'E\\x41'\nD=/tmp/w\nEA\nrm -rf $D/a", "cat <<$'\\105'\nD=/tmp/w\nE\nrm -rf $D/a",
        "cat <<$'\\u0045'\nD=/tmp/w\nE\nrm -rf $D/a")),
]


def fuzz_vp_b():
    """1–4 dòng ghép từ mảnh của các lớp bỏ sót oracle tìm ra: nháy thoát bằng `\\` hay trong comment, heredoc (thân rỗng,
    không nháy đưa vào shell, here-string), biến bị đổi ngoài phép gán thường, cd sau `||`/trong ống, cờ trước -c."""
    DEL = ["rm -rf src", "rm -rf $D/a", 'rm -rf "$D"', "rm -rf ${D}src", "rm -rf src 'x'", "rm -rf dist", "rm -rf /tmp/w/a"]
    STEP = ["D=/", "D=/tmp/w", "D=/tmp/w/", "export D=/tmp/w", "read D <<< /", "eval 'D=/'", "unset D", "D=/tmp/w true",
            "cd /tmp", "cd /tmp/w", "cd dist", "echo it\\'s", "true", "false", "echo D=/tmp/w"]
    LINE = ["bash <<EOF", "bash <<'EOF'", "cat <<'EOF'", "cat <<EOF", "EOF", "# don't", "bash --rcfile f -c 'rm -rf src'",
            "bash -o pipefail -c 'rm -rf src'", "sh -ec 'rm -rf src'", "read D <<< x"]
    rnd = random.Random(2)
    def line():
        if rnd.random() < 0.3:
            return rnd.choice(LINE)
        s = rnd.choice(STEP + DEL)
        for _ in range(rnd.randint(0, 2)):
            s += rnd.choice([" && ", "; ", " || ", " | "]) + rnd.choice(STEP + DEL)
        return "(" + s + ")" if rnd.random() < 0.1 else s
    return ["\n".join(line() for _ in range(rnd.randint(1, 4))) for _ in range(2000)]


def fuzz_vp_c():
    """2–4 khối (dòng lệnh, hay heredoc: dòng mở có khi sau một mảnh số học, 0–2 dòng thân, dòng đóng thường đúng tên)
    ghép từ mảnh của lớp `<<` là dịch bit hay mở heredoc: `((`, `))` trong nháy hay comment, `$[…]`, `$((…))`, số học
    nhiều dòng, `<<` trong nháy, `\\` lẻ hay chẵn cuối dòng, tên heredoc lạ (`E-X`, `$'\\x45'`)."""
    DEL = ["rm -rf src", "rm -rf $D/a"]
    ARITH = ['echo "(("', "echo '))'", '[[ $x == "((" ]]', "echo $[1<<2]", "echo $((1<<2))", "((x=1<<3))",
             "let 'x=1<<2'", "x=$((1+\n2<<n))"]
    STEP = ARITH + ["D=/tmp/w", "cd /tmp/w", "true", "# ((", "# D=/tmp/w"]
    NAMES = [("E-X", "E-X"), ("'Z'", "Z"), ("$'\\x45'", "E")]
    rnd = random.Random(3)
    def block():
        if rnd.random() < 0.4:
            name, close = rnd.choice(NAMES)
            op = (rnd.choice(ARITH) + "; " if rnd.random() < 0.7 else "") + rnd.choice(["cat", "bash"]) + " <<" + name
            body = [rnd.choice(["D=/tmp/w", "cd /tmp/w", "cat <<'Z'", "x"]) for _ in range(rnd.randint(0, 2))]
            return "\n".join([op] + body + [close if rnd.random() < 0.7 else rnd.choice(NAMES)[1]])
        s = rnd.choice(STEP + DEL)
        for _ in range(rnd.randint(0, 2)):
            s += rnd.choice([" && ", "; ", " || ", " | "]) + rnd.choice(STEP + DEL)
        return s + rnd.choice(["", "", "", " \\", " \\\\"])
    return ["\n".join(block() for _ in range(rnd.randint(2, 4))) for _ in range(1000)]
PYEOF

# Lưới của lớp lỗi "thay biến trong thân <<EOF không nháy đưa vào shell", dùng chung cho assert (theo mô hình, chạy mọi nơi)
# và oracle bash của PR #8 (kiểm mô hình bằng bash thật). Reviewer chặn hai vòng liền, mỗi vòng một ví dụ của cùng lớp
# (b06eb79 chỉ sửa biến là đích): lưới đi hết lớp thay vì theo ví dụ.
grid="$tmp/heredoc_grid.py"
cat > "$grid" <<'PYEOF'
def heredoc_grid():
    """[(lệnh, nguy theo mô hình, mô tả)]. Biến X ở vị trí đích, cờ, tên lệnh (rm, hay cd đổi thư mục của rm sau nó) hay
    phần của đích (`${X}src`) trong thân <<EOF hay <<-EOF đưa vào bash hay sh; hai giá trị a, b gán ở hai chỗ: a trước toán
    tử (có khi export), b là gán tạm, sau toán tử (`;`, `&&`, `&`, `|`, `||`) hay trong thân (có khi export); thân tham
    chiếu `$X` hay `\\$X`; có hay không mẹo nháy (`\\'`, `$'…'`) mà chỉ cách đọc strict che đúng. Mỗi chỗ gán xét (a, b) =
    (nguy, mồi) rồi đảo lại. Mô hình: shell cha thay `$X` bằng giá trị tại toán tử heredoc (a); `\\$X` để shell con thay
    bằng env của nó: gán trong thân, không thì gán tạm, không thì a nếu đã export, còn lại rỗng (`${X}src` rỗng là `src`
    của dự án). sh (dash) không biết `$'…'`: nháy mở chuỗi nuốt dòng rm. Mẹo nháy dùng `:` chứ không `echo`: vế trái của
    `|` không in gì nên không chết vì SIGPIPE."""
    # (vị trí, thân, giá trị nguy, giá trị mồi, các giá trị làm bash xoá đệ quy ngoài thư mục tạm)
    POS = [("đích", "rm -rf {}", "/x", "/tmp/w", ("/x",)), ("cờ", "rm {} /x", "-rf", "-f", ("-rf",)),
           ("tên lệnh", "{} -rf /x", "rm", "echo", ("rm",)),
           ("tên lệnh cd", "cd /tmp/w && {} / && rm -rf x", "cd", "true", ("cd",)),
           ("phần của đích", "rm -rf {}src", "/", "/tmp/w/", ("/", ""))]
    OPS = [";", " &&", " &", " |", " ||"]
    # (chỗ gán, trước toán tử, gán tạm, sau toán tử, trong thân, tham chiếu `\$X`)
    PLACES = ([("trước toán tử", "X={a}", "", "", "", False), ("gán tạm", "X={a}", "X={b} ", "", "", False)]
              + [("sau toán tử" + o, "X={a}", "", o + " X={b}", "", False) for o in OPS]
              + [("trong thân", "X={a}", "", "", "X={b}; ", False),
                 ("export trong thân", "X={a}", "", "", "export X={b}; ", False),
                 ("trong thân, \\$", "X={a}", "", "", "X={b}; ", True), ("gán tạm, \\$", "X={a}", "X={b} ", "", "", True),
                 ("export, \\$", "export X={a}", "", "", "", True)]
              + [("export, sau toán tử" + o + ", \\$", "export X={a}", "", o + " X={b}", "", True) for o in OPS])
    TRICKS = [("", ""), (": it\\'s\n", ": 'x'\n"), (": $'a\\'b\\n'\n", ": 'x'\n")]
    out = []
    for pos, body, real, decoy, bad in POS:
        for place, pre, temp, after, inner, esc in PLACES:
            ref = ("\\$" if esc else "$") + ("{X}" if pos == "phần của đích" else "X")
            for a, b in ((real, decoy), (decoy, real)):
                val = (b if inner or temp else a if pre.startswith("export") else "") if esc else a
                for t1, t2 in TRICKS:
                    lines = (t1 + inner.format(b=b) + body.format(ref) + "\n" + t2).splitlines()
                    for sh in ("bash", "sh"):
                        for dash, tab in (("", ""), ("-", "\t")):
                            cmd = (pre.format(a=a) + "; " + temp.format(b=b) + sh + " <<" + dash + "EOF" + after.format(b=b)
                                   + "\n" + "".join(tab + x + "\n" for x in lines) + tab + "EOF")
                            out.append((cmd, val in bad and not (sh == "sh" and "$'" in t1),
                                        f"{pos}, {place}, X={a} rồi {b}, {t1.strip() or 'không mẹo nháy'}, {sh} <<{dash}EOF"))
    return out
PYEOF

# Báo cáo markdown đi qua file, không qua argv: dòng lệnh trên Windows giới hạn 32767 ký tự, ba báo cáo
# cộng lại ~42000 ("Argument list too long" trên Git Bash).
printf '%s' "$md" > "$tmp/md.txt"
printf '%s' "$allmd" > "$tmp/allmd.txt"
printf '%s' "$learnmd" > "$tmp/learnmd.txt"
"$py" - "$out" "$code" "$nofile" "$tmp/md.txt" "$other" "$all" "$plain" "$tmp/allmd.txt" "$learn" "$learncode" "$tmp/learnmd.txt" "$tmp/learn-expect.json" "$review" "$vp" "$tmp" "$grid" <<'PYEOF'
import importlib.util, json, os, sys
for i in (4, 8, 11):  # đường dẫn file báo cáo markdown → nội dung
    sys.argv[i] = open(sys.argv[i], encoding="utf-8").read()
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
for must in ("cd /tmp/x && rm -rf $D/src", "cd /tmp/x && rm -rf `pwd`src", "cd /tmp/x && rm -rf {/,}src",
             "cd /tmp/x && rm -rf $(git rev-parse --show-toplevel)/src"):
    check(must in A, f"đích còn `$`, backtick, `{{` hay `(` không phải đường tương đối với thư mục cd: {must!r}")
for must in ("rm -rf /tmp/x -important", "wsl rm -rf /tmp/x -important"):
    check(must in A, f"rm của BSD thôi nhận cờ ở toán hạng đầu tiên: token sau đó là đích dù mở bằng `-`: {must!r}")
for benign in ("rm C:\\tmp\\x -Recurse", "rd /s /q C:\\tmp\\x"):
    check(benign not in A, f"Remove-Item của PowerShell và cmd nhận tham số sau đích: vô hại: {benign!r}")
for must in ("rm -rf /tmp/link/", "cd /tmp/x && rm -rf link/", "rm -rf node_modules/"):
    check(must in A, f"`/` cuối đích làm rm đi theo symlink, xoá nội dung thư mục mà link trỏ tới: {must!r}")
# Chốt "không có đích ngoài cờ thì báo" của bản cũ phải giữ: thư mục suy từ cd có thể sai (subshell, cd .., cd lỗi)
# và bản cũ báo các ca này chỉ nhờ chốt đó.
for must in ("(cd /tmp && true); rm -rf -- -x", "cd dist && cd .. && rm -rf -- -x", "cd /tmp/w; rm -rf -- -x"):
    check(must in A, f"đích chỉ gồm token mở bằng `-` thì vẫn báo như bản cũ, dù cd trông lành: {must!r}")
for must in ("(cd /tmp && true); rm -rf src", "(cd /tmp && true) && rm -rf src", "cd dist && cd .. && rm -rf src",
             "cd /tmp/w; rm -rf src", "cd /tmp/w\nrm -rf src", "cd /tmp/w || true; rm -rf src", "cd node_modules/ x; rm -rf src",
             "cd /tmp/x & rm -rf src", "cd dist && cd .'.' && rm -rf src", "cd dist && cd .\\. && rm -rf src",
             'cd /tmp/x && cd "-L" && rm -rf src'):
    check(must in A, f"thư mục cd chỉ tin qua `&&` trong cùng phạm vi, đích một token không có `..`: rm chạy ở dự án: {must!r}")
for benign in ("cd /tmp/x && rm -rf y", "cd /tmp/x &&\nrm -rf y", "(cd /tmp/x && rm -rf foo)"):
    check(benign not in A, f"cd vào thư mục tạm rồi `&&` (kể cả xuống dòng sau `&&`, trong subshell) vẫn vô hại: {benign!r}")
for must in ('cd /tmp/x && cd "$(git rev-parse --show-toplevel)" && rm -rf src', "cd /tmp/x && cd $OLDPWD && rm -rf src",
             'cd /tmp/x && cd "$REPO" && rm -rf src', 'cd /tmp/x && cd "`git rev-parse --show-toplevel`" && rm -rf src'):
    check(must in A, f"đích cd còn `$` hay backtick sau khi thay biến đã biết: không biết thư mục: {must!r}")
for must in ("cd /tmp/x && builtin cd .. && rm -rf src", "cd /tmp/x && time cd / && rm -rf home",
             "cd /tmp/x && FOO=1 cd / && rm -rf home", "cd /tmp/x && command cd / && rm -rf home",
             "cd /tmp/x && source ./env.sh && rm -rf src", "cd /tmp/x && . ./env.sh && rm -rf src"):
    check(must in A, f"lệnh đổi thư mục không ở dạng cd đơn đầu đoạn: không biết thư mục: {must!r}")
check("pushd /tmp/x && pushd +1 && rm -rf src" in A, "đích pushd mở bằng `+` xoay ngăn xếp thư mục: không biết thư mục")
for must in ('cd /tmp/x && "cd" /home/p && rm -rf src', "cd /tmp/x && 'cd' /home/p && rm -rf src",
             'cd /tmp/x && c"d" /home/p && rm -rf src', "cd /tmp/x && c\\d /home/p && rm -rf src",
             "cd /tmp/x && $'cd' /home/p && rm -rf src", 'cd /tmp/x && "." ./env.sh && rm -rf src'):
    check(must in A, f"tên lệnh đổi thư mục có nháy hay `\\` vẫn đổi thư mục: không biết thư mục: {must!r}")
check("cd /tmp/x && chdir /home/p && rm -rf src" in A, "zsh có builtin chdir đổi thư mục như cd: không biết thư mục")
check("cd /tmp/x && true & rm -rf src" in A, "`&` chạy nền danh sách có cd ở shell con: lệnh sau `&` chạy ở thư mục cũ")
check("cd /tmp/x && rm -rf y &" not in A, "`&` cuối đoạn chạy nền cả danh sách, rm vẫn ở thư mục cd: vô hại")
for must in ("bash <<'EOF'\nD=/tmp/x\nEOF\nrm -rf $D/src", "bash <<'EOF'\nD=/tmp/x\n# don't\nEOF\necho 'ok'; rm -rf $D/src",
             "bash <<'EOF'; D=/tmp/x\nrm -rf $D/src\nEOF"):
    check(must in A, f"biến gán trong thân heredoc đưa vào shell không ra ngoài, thân chạy trước lệnh sau shell: {must!r}")
check("D=/tmp/x; bash <<'EOF'\nrm -rf $D/src\nEOF" in A, "biến không export của shell cha là rỗng trong thân heredoc (trong nháy)")
check("D=/srv/; cd /tmp/x && bash <<EOF\nrm -rf ${D}y\nEOF" in A, "heredoc không nháy: shell cha thay biến trong thân trước khi đưa vào")
check("export D=/srv/; cd /tmp/x && bash <<'EOF'\nrm -rf ${D}y\nEOF" in A, "biến đã export: shell con thấy giá trị của shell cha")
check("cat <<'EOF' \\\n| bash\nrm -rf src\nEOF" in A, "`\\` cuối dòng mở heredoc kéo `| bash` vào lệnh: thân được đưa vào bash")
for must in ("cd /tmp/w && bash\nrm -rf src", "bash <<'EOF' && cd /tmp/x\nrm -rf src\nEOF",
             "cd /tmp/x && env -C / bash <<'EOF'\nrm -rf home\nEOF", "cd /tmp/x && ssh host bash <<'EOF'\nrm -rf src\nEOF"):
    check(must in A, f"chỉ thân heredoc đưa vào shell mới thừa hưởng thư mục, của chính lệnh shell: {must!r}")
check("cd /tmp/w && bash <<'EOF'\nrm -rf y\nEOF\necho ok" not in A, "thân heredoc đưa vào shell thừa hưởng thư mục cd của lệnh mở")
for must in ("bash <<'EOF'\nD=/home/u\nEOF\ncd /tmp/x && rm -rf $D/src", "bash <<'EOF'\nD=/tmp/y\nEOF\ncd /tmp/x && rm -rf $D/src"):
    check(must in A, f"biến chỉ gán trong thân heredoc đưa vào shell là rỗng sau thân, không phải không biết: {must!r}")
for must in ("D=/srv/app/ bash <<'EOF'\ncd /tmp/x && rm -rf ${D}src\nEOF", "env D=/srv/app/ bash <<'EOF'\ncd /tmp/x && rm -rf ${D}src\nEOF",
             "set -e -a; D=/srv/app/; cd /tmp/x && bash <<'EOF'\nrm -rf ${D}src\nEOF",
             "HOME=/home/u/; cd /tmp/x && bash <<'EOF'\nrm -rf ${HOME}proj\nEOF",
             "D=/srv/app/; bash <<'EOF'\nEOF\ncd /tmp/x && rm -rf ${D}src",
             "D=/srv/app/; bash <<'EOF' && cd /tmp/x && bash\nrm -rf ${D}src\nEOF",
             "cat <<'EOF' \\\n| bash\nEOF\ncd /tmp/x && rm -rf $D/src"):
    check(must in A, f"không đoán export, thân rỗng hay kéo dòng: đọc thêm theo cách cũ rồi lấy hợp: {must!r}")
check("bash <<'EOF' && cd /tmp/x && bash\nrm -rf src\nEOF" in A,
      "thân heredoc chỉ thừa hưởng thư mục khi shell nhận thân là lệnh cuối dòng mở")
for must in ("cd /tmp/x && cd \"-\" && rm -rf src", "cd /tmp/x && cd '-' && rm -rf src"):
    check(must in A, f"cd - trong nháy vẫn về thư mục trước: không biết thư mục: {must!r}")
for must in ("cd /tmp/x || rm -rf src", "cd /tmp/x | rm -rf src"):
    check(must in A, f"`||` và `|` không giữ thư mục cd: {must!r}")
check("D=/tmp/y/; bash <<'EOF'\necho hi\nEOF\nrm -rf ${D}src" not in A, "biến có từ trước thân heredoc giữ giá trị sau thân")
for must in ("bash <<EOF\nD=/tmp/x\nrm -rf $D/src\nEOF", "D=/srv/; bash <<EOF\nD=/tmp/x/\nrm -rf ${D}src\nEOF",
             "cd /tmp/x && bash <<EOF\nD=/tmp/y\nrm -rf $D/src\nEOF"):
    check(must in A, f"heredoc không nháy: shell cha thay biến trước, biến gán trong thân không đổi phép thay: {must!r}")
check("D=/tmp/x/; bash <<EOF\nD=/srv/\nrm -rf \\${D}src\nEOF" in A, "`\\$` trong thân heredoc không nháy: shell con thay biến")
# Báo thừa chấp nhận (như blissful-dirac cd828ea đổi assert của nó): bash xoá /tmp/y/src, nhưng audit không đoán biến của shell
# cha trong thân `<<EOF` không nháy (s86–s91: giá trị đoán từng sai).
check("D=/tmp/y/; bash <<EOF\nrm -rf ${D}src\nEOF" in A, "thân `<<EOF` không nháy: audit không đoán `$D` mà shell cha dùng để thế")
for must in ("export D=/srv/; cat <<'EOF' \\\n| bash\ncd /tmp/x && rm -rf ${D}src\nEOF",
             "export D=/srv/; cat <<'EOF' \\\n| bash\nrm -rf ${D}src\nEOF"):
    check(must in A, f"`\\` cuối dòng mở kéo `| bash`: thân <<'EOF' thấy biến đã export của shell cha: {must!r}")
check("wsl bash -c 'export D=/srv/app/; cd /tmp/x && bash <<\"EOF\"\nrm -rf ${D}src\nEOF'" in A,
      "PowerShell cũng đọc thân heredoc theo cách cũ rồi lấy hợp")
check("D=/srv/a; echo '\x03'; rm -rf ${D}tmp/x" in A, "byte \\x03 có sẵn trong lệnh không phải dấu ở cách đọc cũ")
for must in ("cat > f <<'EOF'\nEOF\nrm -rf src", "cat > f <<EOF\nEOF\nrm -rf src", "cat > f <<-EOF\n\tEOF\nrm -rf src",
             "cat > f <<'EOF'\nEOF\nrm -rf src\nEOF"):
    check(must in A, f"thân heredoc rỗng: dòng ngay sau dòng mở là dấu đóng, lệnh sau đó vẫn chạy: {must!r}")
for must in ("bash <<'EOF'\nEOF\nrm -rf src", "cd /tmp/x && bash <<'EOF'\nEOF\nrm -rf src", "bash <<'EOF'\nrm -rf src"):
    check(must in A, f"thân rỗng hay chưa đóng đưa vào shell vẫn nghi: {must!r}")
check("bash <<EOF\n\tEOF\ncat > f <<'X'\nEOF\nrm -rf src\nX" in A, "`<<EOF` không bỏ tab: `\\tEOF` ở dòng đầu không đóng thân")
for must in ("# don't\nrm -rf src\necho 'x'", "cd /tmp/x # don't\nrm -rf src\necho 'ok'", "echo a \\\\\n# don't\nrm -rf src\necho 'x'"):
    check(must in A, f"nháy trong comment không mở chuỗi: lệnh ở dòng sau vẫn được xét: {must!r}")
check("true | cd /tmp/x && rm -rf y #'\ncat <<'EOF' \\\n# don't $x\nEOF" in A,
      "cách che nháy cũ (không biết comment) vẫn ở trong phép hợp, kể cả ở cách đọc kéo dòng")
for must in ("D=/tmp/y/; bash <<'EOF'\n\x01\nrm -rf ${D}src\nEOF", "bash <<'EOF'\nD=/tmp/x/\n\x02\nEOF\nrm -rf ${D}src"):
    check(must in A, f"byte \\x01–\\x04 có sẵn trong lệnh không phải dấu của cách đọc scoped: {must!r}")
for must in ("bash <<EOF; D=/tmp/x\nrm -rf $D/src\nEOF", "bash <<EOF && D=/tmp/x\nrm -rf $D/src\nEOF",
             "D=/tmp/x/ bash <<EOF\nrm -rf ${D}src\nEOF"):
    check(must in A, f"shell cha thay biến trong thân <<EOF tại toán tử heredoc, trước lệnh sau nó, không thấy gán tạm: {must!r}")
check("D=/srv/x/ bash <<'EOF'\nrm -rf ${D}src\nEOF" in A, "thân <<'EOF': shell con thấy phép gán tạm của chính nó")
for must in ("\x01\ncd /tmp/x # don't\ncd proj; D=/tmp/x/ \\\\\n\x03\ncd /tmp/x # don't\nrm -rf $D/src",
             "'\necho 'a b'\n\x02\n#'\necho ${#x} | D=/tmp/x/ # x \\\nrm -rf $D/src; echo \\#z \\",
             "bash <<'EOF'\nbash <<EOF; D=/tmp/x\n\x03\n(rm -rf $D/src)"):
    check(must in A, f"cách đọc byte \\x01–\\x04 có sẵn thành dấu như 695e799 vẫn trong phép hợp: {must!r}")
for must in ("true || cd /tmp/x && rm -rf y", "true | cd /tmp/x && rm -rf y"):
    check(must in A, f"cd sau `||` có thể bị bỏ qua, cd trong ống chạy ở shell con: không biết thư mục: {must!r}")
for must in ("D=/tmp/x/ true; rm -rf ${D}src", "echo D=/tmp/x/; rm -rf ${D}src", "env D=/tmp/x/ true; rm -rf ${D}src",
             "true;D=/tmp/x/ true;rm -rf ${D}src"):
    check(must in A, f"gán tạm trước lệnh khác hay NAME=VALUE là tham số của lệnh khác không đổi biến của shell: {must!r}")
for benign in ("D=/tmp/x/; rm -rf ${D}src", "export D=/tmp/x/; rm -rf ${D}src"):
    check(benign not in A, f"phép gán đứng riêng hay qua export đổi biến của shell: vô hại: {benign!r}")
for must in ("D=/tmp/x/; bash -s <<'EOF' \\\nEOF\nrm -rf ${D}src\nEOF", "D=/tmp/x/; sh <<'EOF' -s \\\nEOF\nrm -rf ${D}src\nEOF",
             "bash -s <<EOF \\\nEOF\nD=/tmp/x/\nrm -rf ${D}src\nEOF"):
    check(must in A, f"`\\` cuối dòng mở heredoc nối dòng EOF ngay sau vào lệnh, không đóng thân rỗng: {must!r}")
check("cat > f <<'EOF' \\\\\nEOF\nrm -rf src" in A, "`\\\\` chẵn cuối dòng mở heredoc không nối dòng: EOF ngay sau đóng thân rỗng")
for must in ("false && D=/tmp/x/\nbash <<'EOF'\nEOF\nrm -rf ${D}src", "D=/tmp/x/ | true\nbash <<'EOF'\nEOF\nrm -rf ${D}src\nEOF"):
    check(must in A, f"cách đọc scoped với heredoc không nhận thân rỗng (như 6f32d5a) vẫn ở trong phép hợp: {must!r}")
for must in ("false && D=/tmp/x/; rm -rf ${D}src", "true || D=/tmp/x/; rm -rf ${D}src", "D=/tmp/x/ | true; rm -rf ${D}src",
             "true | D=/tmp/x/; rm -rf ${D}src", "D=/tmp/x/&\nrm -rf ${D}src", "export D=/tmp/x/ &\nrm -rf ${D}src"):
    check(must in A, f"phép gán sau `&&`/`||`, trong ống hay chạy nền không đổi biến của shell: {must!r}")
check("cd /tmp/x && $'\\x63d' /home/p && rm -rf src" in A, "từ `$'…'` có escape ANSI-C có thể là cd: không biết thư mục")
for must in ("D=/tmp/x/; bash <<'A' <<'EOF'\nA\nrm -rf ${D}src\nEOF", "D=/tmp/x/; bash <<'A' <<'EOF'\nA\nrm -rf ${D}src\nEOF\nA"):
    check(must in A, f"hai heredoc trên một dòng: cách đọc heredoc không nhận thân rỗng (empty_body=False) vẫn trong phép hợp: {must!r}")
check("D=/tmp/x/; true && D=/srv/; rm -rf ${D}src" in A,
      "phép gán sau `&&` có thể chạy: cách đọc gán lỏng (strict_assign=False) vẫn trong phép hợp")
for must in ("true || # x\ncd /tmp/w && rm -rf src", "true | # x\ncd /tmp && rm -rf src", "true || # a ; b\ncd /tmp/w && rm -rf src",
             "true || # a && b\ncd /tmp/w && rm -rf src", "true | # a | b\ncd /tmp && rm -rf src"):
    check(must in A, f"comment sau `||`/`|` không ngắt: cd ở dòng sau có thể không chạy hay chạy ở shell con: {must!r}")
for must in ("{ D=/tmp/x; } &\nrm -rf $D/src\nwait", "D=/tmp/x && true &\nrm -rf $D/src\nwait",
             "D=/tmp/x && true & true; rm -rf $D/src\nwait", "D=src; { D=/tmp/x; } &\nrm -rf $D\nwait",
             "cd /tmp/khongco src; D=/tmp/w || cd /tmp/w & true; rm -rf $D/src\nwait", "( D=/tmp/x; ); rm -rf $D/src"):
    check(must in A, f"phép gán trong phần chạy nền hay subshell không đổi biến của shell cha: {must!r}")
check("D=/tmp/x; { true; } &\nrm -rf $D/src\nwait" not in A, "phép gán ở shell cha trước phần chạy nền vẫn áp: vô hại")
check("D=/tmp/x; bash <<EOF\nrm -rf \\$D/src\nEOF" in A, "`\\$` trong thân `<<EOF` không nháy: shell con thay bằng env của nó")
for must in ("if false; then\nD=/tmp/x\nfi\nbash <<EOF\nrm -rf $D/src\nEOF", "cat <<\\EOF\nD=/tmp/x\nEOF\nbash <<EOF\nrm -rf $D/src\nEOF",
             "cat <<EOF >/dev/null\nx\n EOF\nD=/tmp/x\nEOF\nbash <<EOF\nrm -rf $D/src\nEOF",
             "echo 'a;D=/tmp/x;b'; cat <<EOF | bash\nrm -rf $D/src\nEOF", "D=/tmp/x; unset D; bash <<EOF\nrm -rf $D/src\nEOF",
             "declare -u D; D=/tmp/x; bash <<EOF\nrm -rf $D/src\nEOF", "PWD=/tmp/x; cd src; bash <<EOF\nrm -rf $PWD\nEOF",
             "D=/tmp/x; bash -s $[D=5] <<EOF\nrm -rf $D/src\nEOF", "RANDOM=/tmp/x; bash <<EOF\nrm -rf $RANDOM/src\nEOF",
             "_=/tmp/x; bash <<EOF\nrm -rf $_/src\nEOF"):
    check(must in A, f"thân `<<EOF` không nháy chỉ thấy biến mà phép gán chắc đã chạy ở shell cha: {must!r}")
check("D=/tmp/x; bash <<EOF\nrm -rf $D/src\nEOF" in A, "thân `<<EOF` không nháy: audit không đoán `$D` mà shell cha dùng để thế")
for must in ("D=/tmp/x\nwhile bash <<EOF\nrm -rf $D/src\ntest -n \"$D\"\nEOF\ndo unset D\ndone",
             "D=/tmp/x\nbash <<EOF.x\ntrue\nEOF.x\nunset D\nrm -rf $D/src", "D=/tmp/x\nbash <<EOF-1\nEOF-1\nD=\nrm -rf $D/src",
             "D=/tmp/x\nbash <<EOF\r\ntrue\nEOF\r\nunset D\nrm -rf $D/src", "D={/tmp/,/}x\nbash <<EOF\nrm -rf $D/src\nEOF",
             "D=/tmp/x,/\nbash <<EOF\nrm -rf {$D}/src\nEOF"):
    check(must in A, f"audit không đoán biến của shell cha trong thân `<<EOF` không nháy (vòng lặp, delimiter lạ, brace): {must!r}")
for must in ("cat <<'EOF'\nEOF\nrm -rf src", "cd /tmp && rm -rf $D",
             "true | cd /tmp && rm -rf src", "( D=/tmp/x ); rm -rf $D/src",
             "true || cd /tmp/w && rm -rf src", "test -d /tmp/w || cd /tmp/w && rm -rf src",
             "cd src || cd /tmp/w && rm -rf build2", "cd /tmp/w && true & rm -rf src",
             "cd /tmp/w && rm -rf a & rm -rf src", "bash <<EOF\nD=/tmp/x; rm -rf $D/src\nEOF",
             "cat <<EOF | bash\nexport D=/tmp/x\nrm -rf $D/src\nEOF", "D=src; bash <<EOF\nD=/tmp/x; rm -rf $D\nEOF",
             "bash <<EOF; D=dist\nrm -rf $D/src\nEOF", "bash <<EOF && cd dist\nD=/tmp/x; rm -rf $D/src\nEOF",
             "D=/tmp/x bash <<EOF\nrm -rf $D/src\nEOF", "D=/tmp/x cat <<EOF | bash\nrm -rf $D/src\nEOF",
             "false && D=/tmp/x\nbash <<EOF\nrm -rf $D/src\nEOF", "true || D=/tmp/x\ncat <<EOF | bash\nrm -rf $D/src\nEOF",
             "D=src | D=/tmp/x\nbash <<EOF\nrm -rf $D/src\nEOF", "echo D=/tmp/x; cat <<EOF | bash\nrm -rf $D/src\nEOF",
             "true # D=/tmp/x\nbash <<EOF\nrm -rf $D/src\nEOF", 'echo " D=/tmp/x"; bash <<EOF\nrm -rf $D/src\nEOF',
             "true # it's\necho 'a; D=/tmp/x; b'; bash <<EOF\nrm -rf $D/src\nEOF", "bash <<EOF;D=dist\nrm -rf $D/src\nEOF"):
    check(must in A, f"lệnh blissful-dirac nền bỏ sót, port youthful-fermi phải bắt: {must!r}")
for must in ("rm -rf /tmp/$X", "cd /tmp && rm -rf node_modules/$X", "(D=..); rm -rf node_modules/$D"):
    check(must in A, f"biến audit không thay được có thể chứa `..`, khoảng trắng hay đường tuyệt đối, dù sau thư mục tạm hay "
                     f"tên lành: {must!r}")
# Port blissful-dirac 55a62d6, 73226cf, 5b32600, 98b74d0 và ca P3 (fixture s101–s143): biến chỉ đổi theo phép gán thuần chắc
# chạy ở shell này, chỗ khác làm biến thành không biết. Lệnh phải vào A, và có nhãn xoá đệ quy (kiểm sau khi nạp audit-agent).
P3_MUST = ("true D=dist; rm -rf $D/src", "make PREFIX=/tmp/x install; rm -rf $PREFIX/lib", "D=/tmp/x true; rm -rf $D/src",
             "D=/tmp/x | true; rm -rf $D/src", "echo D=/tmp/x; rm -rf $D",
             "D=/tmp/x; { D=..; }; true D=/tmp/x; rm -rf node_modules/$D", "D=/tmp/x; D=.. # c\ntrue D=/tmp/x; rm -rf node_modules/$D",
             "echo a\\|#b | # c\nexport D=/tmp/x; rm -rf $D/src", "local D=/tmp/x; rm -rf $D/src", "D=/tmp/x; D=; rm -rf $D/src",
             'D=/tmp/x; D=""; rm -rf $D/src', "D=/tmp/x; unset D; rm -rf $D/src", "D=/tmp/x; D= E=/tmp/y; rm -rf $D/src",
             "D=/tmp/x; export D=; rm -rf $D/src", "D=/tmp/x; { unset -v D; }; rm -rf $D/src",
             "f() { true; D=/tmp/w; local D=..; true D=/tmp/y; rm -rf node_modules/$D; }; f",
             "D=..; if false; then D=; fi; true D=/tmp/y; rm -rf node_modules/$D",
             "D=..; f() { true; D=; }; true D=/tmp/y; rm -rf node_modules/$D", "if false; then D=/tmp/z; fi; rm -rf $D/src",
             "false && D=/tmp/x; rm -rf $D/src", "while false; do D=/tmp/x; done; rm -rf $D/src",
             "if true; then echo a\\; fi; else D=/tmp/x; fi; rm -rf $D/src",
             "if false; then x=$(if true; then echo; fi); D=/tmp/x; fi; rm -rf $D/src",
             "D=/tmp/x; function f { D=..; }; f; true D=/tmp/y; rm -rf node_modules/$D",
             'D=/tmp/w; read -aD <<< /etc; rm -rf "$D"', "D=/tmp/w; unset D -f; rm -rf $D/a",
             "D=../.. # a\n{ D=~; } | true && rm -rf node_modules/$D", "D=../..; local D=/tmp/w; rm -rf node_modules/$D",
             "export D=../..; { D=/tmp/w; } | true | rm -rf dist/$D",
             "cat <<'EOF' | bash\nD=~; D=\"x /\"; D=/tmp/w & true; rm -rf /tmp/w/$D\nEOF",
             "D=/; false && # c\nD=/tmp/x; rm -rf $D/src", "D=/; false &&\n\n# c\n\nD=/tmp/x\nrm -rf $D/src",
             "D=/; ( case a in a) :;; esac; D=/tmp/x; ); rm -rf $D/src", "f() { D=/; }; D=/tmp/x; F=f; $F; rm -rf $D/src",
             "export() { D=/; }; D=/tmp/w; export D=/tmp/x; rm -rf $D/src",
             "bash <<< 'rm -rf src'", "D=/tmp/w; sh <<< \"rm -rf $D/..\"", "cat <<< 'rm -rf src' | bash",
             "D=/tmp/w; bash <<< \"D=/; rm -rf \\$D/src\"", "# bash <<< '\ncat <<'E-X'\nD=/tmp/w\nE-X\nrm -rf $D/a\n# '",
             "echo \"bash <<< '\"; cat <<'E-X'\nD=/tmp/w\nE-X\nrm -rf $D/a\necho \"'\"")
for must in P3_MUST:
    check(must in A, f"phép gán không thuần hay có thể không chạy ở shell này không đặt biến: {must!r}")
# Vô hại theo bash 5.2 (xoá trong /tmp/x): phép gán thuần, export, lệnh ghép và thân hàm đã đóng, phép gán trước `&&`,
# `export D` giữ giá trị, `unset -f` bỏ hàm.
for benign in ("D=/tmp/x; rm -rf $D/src", "export D=/tmp/x; rm -rf $D/src", "D=/tmp/x E=/tmp/y; rm -rf $D $E",
               "D=/tmp/x; export D; rm -rf $D/src", "D=/tmp/x; unset -f D; rm -rf $D/src",
               "if true; then :; fi; D=/tmp/x; rm -rf $D/src", "f() { :; }; D=/tmp/x; rm -rf $D/src",
               "x=$(for i in 1; do echo; done); D=/tmp/x; rm -rf $D/src", "D=/tmp/x && rm -rf $D/src"):
    check(benign not in A, f"phép gán thuần chắc chạy ở shell này đổi biến: vô hại: {benign!r}")
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
for must in P3_MUST:
    check("xoá đệ quy" in a.suspicious_labels(must, a.SUSPICIOUS), f"P3: nhãn xoá đệ quy: {must!r}")
# Cách đọc pure tìm định nghĩa hàm trên từng đoạn: chuỗi ngoặc dài không được làm regex quay lui bậc hai (reviewer đo
# `"{"*40000 + " $D"` 18 giây trước khi sửa, nền 0,07 giây).
import time
for cmd in ("{" * 40000 + " $D", "}" * 40000 + " $D", "{a" * 20000 + " $D", "a" * 40000 + "() $D"):
    t0 = time.time()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    check(time.time() - t0 < 1, f"cách đọc pure tuyến tính trên chuỗi ngoặc dài: {cmd[:12]!r}… mất {time.time() - t0:.1f} s")
# Cách đọc bash dò here-string theo từng `<<<`: dòng dài có nhiều `<<<` không được làm nó bậc hai (reviewer đo 7,9–91 giây
# trước khi sửa, nền 0,3–1 giây).
for cmd in ("read D<<<x; " * 3000, "wc <<< x; " * 5000, 'grep a <<< "$x" && ' * 3000, "echo hi; " * 20000 + "<<< a " * 4000):
    t0 = time.time()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    check(time.time() - t0 < 4, f"cách đọc bash tuyến tính trên nhiều here-string: {cmd[:14]!r}… mất {time.time() - t0:.1f} s")
check(a.project_key("C:\\vnstock-trial") == "C--vnstock-trial", "tên thư mục phiên cho đường dẫn Windows")
check(a.project_key("/home/user") == "-home-user", "tên thư mục phiên cho đường dẫn Linux")
for cmd, want in (("rm -rf /tmp/x\\\nsrc", ["rm -rf /tmp/xsrc"]), ("echo a\\\\\nrm -rf src", ["echo a\\\\", "rm -rf src"])):
    got = [full for _p, full, _c, _s in a.segments(cmd)]
    check(got == want, f"segments nối dòng như bash (`\\` + xuống dòng bị bỏ, `\\\\` + xuống dòng là hai lệnh): {cmd!r} -> {got!r}")
# PowerShell nối dòng bằng backtick, `\` cuối dòng chỉ là dấu phân cách đường dẫn.
got = [full for _p, full, _c, _s in a.segments("Remove-Item -Recurse C:\\x\\\nsrc", "PowerShell")]
check(got == ["Remove-Item -Recurse C:\\x\\", "src"], f"PowerShell không nối dòng tại `\\`: {got!r}")
# Guard hỏi lệnh này (` /)` trông như đích /), nên không vào A: kiểm thẳng. Bash thay $(echo /) rồi xoá /src.
check("xoá đệ quy" in a.suspicious_labels("cd /tmp/x && rm -rf $(echo /)src", a.SUSPICIOUS),
      "đích mở bằng lệnh lồng không phải đường tương đối với thư mục cd: cd /tmp/x && rm -rf $(echo /)src")
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
# Lệnh có sẵn chuỗi trùng dạng chỗ giữ nháy (byte NUL, số, NUL) không được làm audit chết: một lệnh ném lỗi là mất cả báo cáo.
# `\` cuối dòng mở heredoc kéo dòng thân vào lệnh nên chuỗi đó tới được chỗ tra.
for cmd in ("cat <<EOF \\\n\x000\x00\nEOF\nrm -rf src", "echo \x000\x00; rm -rf src", "echo \x00" + "1" * 5000 + "\x00; rm -rf src"):
    try:
        got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    except Exception as exc:
        got = exc
    check(isinstance(got, list) and "xoá đệ quy" in got,
          f"chuỗi trùng chỗ giữ nháy không làm audit chết, rm vẫn nghi: {cmd[:40]!r}: {str(got)[:120]}")
# SHELL_C và mẫu filter-branch của 1667825 quét lại bậc hai: lần khớp từ mỗi shell trong `bash -bash -bash …` đi lại chuỗi
# cờ tới cuối, `.*` từ mỗi `git` đi lại tới cuối dòng (7–26 giây mỗi lệnh dưới đây ở 1667825).
import random, re, time
slow = []
for cmd in ("bash" + " -bash" * 5000, "sh" + " -sh" * 5000, "zsh" + " -zsh" * 5000, "dash.exe" + " -dash" * 5000,
            "pwsh" + " -pwsh" * 5000, "powershell" + " -powershell" * 3000, "Bash" + " -BAſH" * 5000, "bash" + " -x -bash" * 3000,
            "git-bash" + " --x-git-bash" * 5000, "git " * 10000, "GIT filter-" * 5000, "git" + " -git" * 5000,
            'D="' + "\n".join(["git " * 2500] * 4) + '"; echo $D'):  # $D thay vào: dòng có `\n`, mỗi dòng nhiều git
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:16], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên chuỗi cờ trùng tên shell hay dòng nhiều git (đầu lệnh, giây): {slow}")
# Biến có `\n` thay vào bản so mẫu: mẫu filter-branch vẫn xét từng dòng như mẫu cũ.
for cmd, want in (('D="x\ngit filter-branch"; echo $D', ["viết lại lịch sử git"]), ('D="git x\nfilter-branch"; echo $D', [])):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check(got == want, f"git và filter-… phải cùng dòng, ở dòng nào cũng được: {cmd!r}: {got!r}")
# Bản tuyến tính phải khớp đúng những chuỗi mẫu cũ khớp (giữ nguyên văn bản mẫu cũ ở đây): chuỗi ngẫu nhiên ghép từ tên
# shell (hoa thường, ſ), cờ (cả cờ trùng tên shell, `-shx`), `/c`, K Kelvin, `|`, eval, git (`GIT`, `gıt`), filter-…,
# khoảng trắng Unicode, `\n`, `\r`. Lô phải đi qua chỗ khó: lần khớp cũ đi qua cờ `-<shell>`, dòng nhiều git trước filter-….
OLD_SHELL_C = re.compile(r"\b(bash|sh|zsh|dash|pwsh|powershell)(\.exe)?\s+(-\w+\s+)*-c(ommand)?\s|\bcmd(\.exe)?\s+(/\w\s+)*/[ck]\s"
                         r"|\beval\s|\|\s*(bash|sh|zsh|dash|pwsh|powershell)(\.exe)?\b", re.IGNORECASE)
OLD_FILTER = re.compile(r"\bgit\b.*\bfilter-(branch|repo)\b", re.IGNORECASE)
new_filter = [re.compile(rx, re.IGNORECASE) for rx, label in a.SUSPICIOUS if label == "viết lại lịch sử git"]
check(len(new_filter) == 1, f"SUSPICIOUS phải có đúng một mẫu nhãn 'viết lại lịch sử git', có {len(new_filter)}")
WORDS = ["bash", "sh", "zsh", "dash", "pwsh", "powershell", "Bash", "SH", "baſh", "bash.exe", "cmd", "CMD.exe", ".exe", "eval", "|",
         "-", "-c", "-C", "-command", "-x", "-bash", "-sh", "-SH", "-shx", "-ſh", "-pwsh", "-powershell", "-zsh", "-dash", "-ommand",
         "-cmd", "/c", "/k", "/x", "git", "GIT", "gıt", "-git", "git-bash", "filter-branch", "filter-repo", "FILTER-REPO",
         "filter-", "branch", "x", "\u212a", "_", "é", "1"]
SEPS = [" ", " ", " ", " ", "  ", "\t", "\n", "\n", "\r", "\x0b", "\u00a0", "", ""]
rnd = random.Random(3)
diff, through, multi = [], 0, 0
for _ in range(8000):
    s = "".join(rnd.choice(WORDS) + rnd.choice(SEPS) for _ in range(rnd.randint(1, 8)))
    for old, new in ((OLD_SHELL_C, a.SHELL_C), (OLD_FILTER, new_filter[0] if new_filter else None)):
        mo, mn = old.search(s), new and new.search(s)
        if bool(mo) != bool(mn):
            diff.append(s)
        elif mo and old is OLD_SHELL_C:
            through += bool(re.search(r"\s-(bash|sh|zsh|dash|pwsh|powershell)\s", mo.group(0), re.IGNORECASE))
        elif mo:
            multi += len(re.findall(r"\bgit\b", mo.group(0), re.IGNORECASE)) > 1
check(not diff, f"SHELL_C và mẫu filter-branch phải khớp đúng những chuỗi mẫu cũ khớp: {len(diff)} chuỗi khác, vd {diff[:3]!r}")
check(through >= 20 and multi >= 10, f"lô vi sai phải đi qua cờ `-<shell>` ({through}) và dòng nhiều git ({multi})")
# Thân `bash -c '…'` (cả cờ gộp -lc) là chương trình của shell con: biến không export của shell cha là rỗng trong thân, biến
# gán trong thân không ra ngoài. Đích ghi bên cạnh là đích bash 5.2 xoá thật (rm thay bằng echo), thư mục /tmp/w không có.
for cmd in ("D=/tmp/w; bash -c 'D=/; rm -rf $D'",               # xoá /
            "D=/tmp/w; sh -c 'rm -rf $D/a'",                     # D không export: xoá /a
            "D=/tmp/w; cd /tmp && sh -c 'rm -rf $D/a'",          # xoá /a
            "bash -lc 'rm -rf /'",
            "D=/; bash -c 'true; D=/tmp/w'; rm -rf $D",          # D gán trong thân không ra shell cha: xoá /
            "D=/; bash -c \"true; D=/tmp/w\"; rm -rf $D",
            'D=/tmp/w; bash -c "rm -rf \\$D/a"',                 # \$ trong nháy kép: shell con tự thay D (rỗng), xoá /a
            "bash -c \"true; D=/tmp/w; bash -c 'rm -rf \\$D/a'\""):  # lồng nhau: D không export sang shell cháu, xoá /a
    check(a.suspicious_labels(cmd, a.SUSPICIOUS), f"thân bash -c là phạm vi shell con: {cmd!r}")
# Thân -c của shell cục bộ trơn thừa hưởng thư mục cd, biến có từ trước lấy lại giá trị sau thân, kể cả thân lồng nhau.
for cmd in ("cd /tmp/w && bash -c 'rm -rf src'", "D=/tmp/y/; bash -c 'echo hi'; rm -rf ${D}src",
            "D=/tmp/y/; bash -c \"bash -c 'echo hi'\"; rm -rf ${D}src"):
    check(not a.suspicious_labels(cmd, a.SUSPICIOUS), f"thân bash -c vô hại không được thành nghi: {cmd!r}")
got = [full for _p, full, _c, _s in a.segments('bash -c "rm -rf \\"a b\\" \\$D"', exact=True)]
check(got == ["bash", 'rm -rf "a b" $D'], f"thân -c nháy kép gỡ thoát như bash (`\\\"` thành `\"`, `\\$` thành `$`): {got!r}")
# Nháy lẻ trong thân heredoc đưa vào shell hay trong comment không ghép với nháy của lệnh sau thành một chuỗi nuốt rm.
# cd lỗi thì rm sau EOF chạy ở thư mục dự án.
for cmd, tool in (("cd /tmp/w && bash <<'EOF'\n# don't\nEOF\nrm -rf src 'x'", "Bash"),
                  ("cd /tmp/w && bash <<'EOF'\necho don't\nEOF\nrm -rf src 'x'", "Bash"),
                  ("# Clean build artifacts (don't touch src)\nrm -rf build 'some dir'", "Bash"),
                  ("# don't\nrm -rf src 'x'", "Bash"), ("# don't\nRemove-Item -Recurse src 'x'", "PowerShell")):
    check(a.suspicious_labels(cmd, a.SUSPICIOUS, tool), f"nháy không ghép qua thân heredoc hay comment: {tool} {cmd!r}")
check(not a.suspicious_labels("# don't\nrm -rf node_modules 'dist'", a.SUSPICIOUS), "comment có nháy lẻ: đích vô hại vẫn vô hại")
# `\` + xuống dòng giữa shell và `<<`: bash nối thành một lệnh, thân heredoc là lệnh của shell đó.
for cmd in ("bash \\\n<<'EOF'\nrm -rf src\nEOF", "bash \\\n  -s <<'EOF'\nrm -rf src\nEOF",
            "bash \\\n<<'EOF'\n# x \\\nD=/; rm -rf $D\nEOF"):  # `\` cuối comment trong thân là chữ: bash xoá /
    check(a.suspicious_labels(cmd, a.SUSPICIOUS), f"dòng mở heredoc nối qua `\\`: thân đưa vào bash là lệnh: {cmd!r}")
# `\` cuối comment là chữ, bash chạy rm ở dòng sau: cách đọc exact cũng phải đọc không nối dòng (nối thì rm vào comment).
check(a.suspicious_labels("# don't \\\nrm -rf src 'x'", a.SUSPICIOUS), "`\\` cuối comment có nháy lẻ: rm ở dòng sau vẫn nghi")
# Cờ trước cụm c: cờ dài, `-o`/`-O` kèm tên, cụm cờ ngắn kết thúc bằng o kèm tên, `--` sau cụm c. Bash 5.2 vẫn chạy thân
# (rm thay bằng echo), mà mọi cách đọc khác che thân như một chuỗi.
for cmd, label in (("bash -o pipefail -c 'rm -rf /'", "xoá đệ quy"), ("bash --login -c 'rm -rf /'", "xoá đệ quy"),
                   ("bash -euo pipefail -c 'rm -rf /'", "xoá đệ quy"), ("bash -O extglob -c 'rm -rf /'", "xoá đệ quy"),
                   ("bash --norc --noprofile -c 'git push --force origin main'", "force-push / xoá nhánh remote"),
                   ("D=/tmp/w; bash -euo pipefail -c 'D=/; rm -rf $D'", "xoá đệ quy"),  # xoá /
                   ("D=/tmp/w; bash -c -- 'rm -rf $D/a'", "xoá đệ quy"),                # xoá /a
                   # chỉ cách đọc exact có nối dòng thấy `bash -c`: xoá /
                   ("D=/tmp/w; bash \\\n  -c 'D=/; rm -rf $D'", "xoá đệ quy")):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check(label in got, f"cờ trước -c, `--` sau -c, `\\` + xuống dòng trước -c: thân vẫn là lệnh: {cmd!r}: {got!r}")
# Cụm cờ dài hay chuỗi cờ dài không làm audit chậm: regex thân -c không được backtrack bậc hai hay mũ (cụm c
# `-[A-Za-z]*c[A-Za-z]*` mất ~20 giây với 30000 chữ c), lần khớp từ một shell không quét lại qua các shell sau trong chuỗi
# cờ (`bash -o bash -o …` mất ~14 giây khi tên của -o nhận cả shell). Bản tuyến tính mất dưới 0,2 giây mỗi ca.
import time
slow = []
for cmd in ("sh -" + "c" * 30000, "bash -" + "c" * 16000, "bash" + " -o" * 5000 + " x", "bash" + " --a" * 5000,
            "bash" + " -euo pipefail" * 3000, "bash -o " * 5000, "bash" + " --bash" * 5000):
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:16], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên cụm cờ dài (đầu lệnh, giây): {slow}")
# Shell có tiền tố chữ nối bằng `-` (git-bash của Git for Windows) vẫn gỡ thân -c như 96f49a6. Cách đọc khác không bù
# được: SHELL_C không nhận cụm `-lc`, còn với `-c` trơn chúng thế env của cha vào thân.
for cmd in ("git-bash -lc 'rm -rf /'", "git-bash.exe -lc 'rm -rf /'", "D=/tmp/w; git-bash -c 'D=/; rm -rf $D'"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"shell có tiền tố chữ nối bằng `-`: thân -c vẫn là lệnh: {cmd!r}: {got!r}")
# Dấu SNAP (chỗ toán tử heredoc, 8dc3d0d) chỉ đặt ở cách đọc parent_env: chen giữa shell và cờ (`bash <<EOF -c '…'`) nó làm
# cách đọc exact không gỡ được thân -c (reviewer). Bash 5.2: thân -c chạy, xoá $HOME/proj, ~ hay / (X không export).
for cmd in ("D=/tmp/x; bash <<EOF -c 'D=$HOME/proj; rm -rf $D'\nEOF", "D=/tmp/x; bash <<'EOF' -lc 'D=~; rm -rf $D'\nEOF",
            "X=/tmp/a; bash <<EOF -c 'rm -rf $X'\nEOF"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"toán tử heredoc giữa shell và -c: thân -c vẫn là phạm vi shell con: {cmd!r}: {got!r}")
# Thân <<EOF có sẵn mọi ký tự mà cách đọc parent_env từng dùng làm chỗ giữ cho `\$` (reviewer): không được ném lỗi làm sập
# cả báo cáo, rm vẫn nghi.
for cmd in ("bash <<EOF\nrm -rf src \x06\ue000\ue001\ue002\nEOF", "D=/tmp/x; bash <<EOF\nrm -rf \\$D/src \x06\ue000\ue001\ue002\nEOF"):
    try:
        got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    except Exception as exc:
        got = exc
    check(isinstance(got, list) and "xoá đệ quy" in got, f"ký tự lạ trong thân <<EOF không làm audit chết, rm vẫn nghi: {cmd!r}: {got!r}")
# Shell nhận cả sau `-` thì cờ và tên của -o không được đi qua chỗ một shell khác mở (`--x-bash`, `-o x-bash`): lần khớp
# từ mỗi shell quét lại tới cuối chuỗi cờ, bậc hai (~10 giây với cờ dài `--\w[\w-]*`, ~6 giây với tên `\w[\w-]*`).
# `bash -bash …`, `git-bash --x-git-bash …` (chậm từ 27727f5 do SHELL_C và mẫu filter-branch) có assert riêng ở khối sau
# "chuỗi trùng chỗ giữ nháy".
slow = []
for cmd in ("bash" + " --x-bash" * 5000, "x-bash -o x-bash" * 3000, "bash" + " -o x-bash" * 3000):
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:16], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên chuỗi cờ có shell sau `-` (đầu lệnh, giây): {slow}")
# Cờ `+` (`+e`, cụm `+c`), cờ sau cụm c (`-c -x`, `-c -o pipefail`), tên của -o trong nháy hay có `-`, `--rcfile`/`--init-file`
# kèm tham số, cụm c có o kèm tên (`-co pipefail`, `-oc pipefail`, `-cO extglob`): bash 5.2 vẫn chạy thân (rm thay bằng echo,
# đích ghi bên cạnh), mà mọi cách đọc khác che thân như một chuỗi. `--login` trước `-c +e` và `-c -o pipefail`: không có nó thì
# SHELL_C nhận `bash -c`, thân không bị che và `+e`, `pipefail` bị coi là đích của rm, nên đã nghi sẵn mà không nhờ gỡ thân.
for cmd in ("bash +e -c 'rm -rf /'", "D=/tmp/w; bash +e -c 'rm -rf $D/a'",  # xoá /a
            "D=/tmp/w; bash +e -c 'D=/; rm -rf $D'",                         # xoá /
            "D=/tmp/w; bash -c -x 'rm -rf $D/a'", "D=/tmp/w; bash -c -x 'D=/; rm -rf $D'",
            "D=/tmp/w; bash -o pipefail -c -e 'rm -rf $D/a'",
            "bash -o 'pipefail' -c 'rm -rf /'", "D=/tmp/w; bash -o 'pipefail' -c 'rm -rf $D/a'",
            "D=/tmp/w; bash -o \"pipefail\" -c 'rm -rf $D/a'",
            "bash -o interactive-comments -c 'rm -rf /'", "D=/tmp/w; bash -o interactive-comments -c 'rm -rf $D/a'",
            "bash --rcfile /dev/null -c 'rm -rf /'", "D=/tmp/w; bash --rcfile /dev/null -c 'rm -rf $D/a'",
            "D=/tmp/w; bash --init-file x -c 'rm -rf $D/a'", "D=/tmp/w; bash --login --rcfile x -c 'rm -rf $D/a'",
            "bash -co pipefail 'rm -rf /'", "D=/tmp/w; bash -co pipefail 'rm -rf $D/a'",
            "D=/tmp/w; bash -oc pipefail 'rm -rf $D/a'", "D=/tmp/w; bash -cO extglob 'rm -rf $D/a'",
            "D=/tmp/w; bash +c 'rm -rf $D/a'", "D=/tmp/w; bash +ec 'rm -rf $D/a'",
            "D=/tmp/w; bash --login -c +e 'rm -rf $D/a'", "D=/tmp/w; bash --login -c -o pipefail 'rm -rf $D/a'",
            "D=/tmp/w; bash +x -c -o 'pipefail' 'rm -rf $D/a'"):  # thử `-o` trơn trước `-o tên` thì `'pipefail'` thành thân
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"cờ `+`, cờ sau cụm c, tên của -o, --rcfile, cụm c có o: thân vẫn là lệnh: {cmd!r}: {got!r}")
# Các dạng cờ trên không làm regex thân -c chậm. Cờ trước cụm c không được giống cụm c: không thì `bash -c -c …` (không thân)
# thử cụm c ở từng `-c` rồi quét cờ sau tới cuối, bậc hai từ một shell. Tham số của --rcfile không mở bằng `-`/`+`: không thì
# `--rcfile --rcfile …` tách được theo Fibonacci cách. Cờ `+`, tên, tham số không đi qua chỗ một shell khác mở (`+bash`,
# `-o x-bash` sau cụm c, `--rcfile bash`, `--rcfile /bash`, `--rcfile /bash.exe`).
slow = []
for cmd in ("bash -c" + " -x" * 10000, "bash" + " -c" * 10000, "bash" + " +c" * 10000, "bash" + " +e" * 5000,
            "bash" + " -o 'x'" * 5000, "bash" + " -o a-b" * 5000, "bash" + " --rcfile /x" * 5000,
            "bash" + " --rcfile /bash" * 5000, "bash -c" + " -o x-bash" * 3000, "bash" + " -co x" * 5000,
            "bash -c -x " * 3000, "bash" + " -o bash" * 5000, "bash" + " --rcfile bash" * 5000,
            "bash" + " --rcfile /bash.exe" * 5000, "bash" + " +bash" * 5000, "bash" + " --rcfile" * 5000,
            "bash" + " --rcfile +x" * 5000):
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:24], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên chuỗi cờ `+`, cờ sau cụm c, tên, --rcfile (đầu lệnh, giây): {slow}")
# Cách đọc strict: thân -c gỡ bằng regex mở rộng của 0a8cd90 (cách đọc exact giữ regex của 1667825). `-` lẻ sau cụm c kết
# thúc cờ như `--`: bash 5.2 vẫn chạy thân (`bash - -c` thì không). Đích bash xoá thật ghi bên cạnh (rm thay bằng echo).
for cmd, tool in (("bash -c - 'rm -rf /'", "Bash"), ("bash -lc - 'rm -rf /'", "Bash"),
                  ("D=/tmp/w; bash -c - 'D=/; rm -rf $D'", "Bash"),  # xoá /
                  ("D=/tmp/w; sh -c - 'rm -rf $D/a'", "Bash"),       # xoá /a
                  ("D=/tmp/w; bash -lc - 'rm -rf $D/a'", "Bash"),    # xoá /a
                  # PowerShell cũng đọc strict: không thì mất phần gỡ thân của 0a8cd90 (cờ `+`) mà exact không còn làm
                  ("bash +e -c 'rm -rf /'", "PowerShell"), ("bash -lc - 'rm -rf /'", "PowerShell")):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS, tool)
    check("xoá đệ quy" in got, f"`-` lẻ sau cụm c, cờ `+`: thân -c vẫn là lệnh: {tool} {cmd!r}: {got!r}")
# Chỗ các cách đọc khác lệch làm rm trông vô hại, cách đọc strict đọc như bash 5.2 (rm thay bằng echo, xoá src ở thư mục dự
# án): `\'`, `\"` ngoài nháy là ký tự thoát, không mở chuỗi nuốt lệnh sau; thân heredoc rỗng (dòng đóng ngay sau dòng mở).
for cmd in ("echo it\\'s\nrm -rf src 'x'", "echo it\\'s; rm -rf src 'x'", 'echo a\\"b\nrm -rf src "x"',
            "cat <<'EOF'\nEOF\nrm -rf src", "cat <<EOF\nEOF\nrm -rf src", "cat > f <<'EOF'\nEOF\nrm -rf src"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"nháy thoát ngoài chuỗi, thân heredoc rỗng: rm vẫn là lệnh: {cmd!r}: {got!r}")
for cmd in ("cd /tmp/w && rm -rf src", "D=/tmp/w; rm -rf $D", "cat <<'EOF'\nrm -rf src\nEOF", "cat <<'EOF'\n\nrm -rf src\nEOF",
            "echo it\\'s; rm -rf node_modules 'dist'"):
    check(not a.suspicious_labels(cmd, a.SUSPICIOUS), f"cách đọc strict không biến lệnh vô hại thành nghi: {cmd!r}")
# Thân <<EOF không nháy: cách đọc strict thay `$D` bằng giá trị của shell cha như bash (xoá /tmp/x/a). Phép hợp vẫn báo lệnh
# này vì cách đọc blank không đoán biến của shell cha (sc1, báo thừa có chủ ý), nên kiểm thẳng đoạn rm của cách đọc strict.
got = [f for j in (False, True) for _p, f, _c, _s in a.segments("D=/tmp/x; bash <<EOF\nrm -rf $D/a\nEOF", "Bash", j,
                                                                exact=True, strict=True) if "rm" in f]
check(got == ["rm -rf /tmp/x/a"] * 2, f"cách đọc strict thay biến của shell cha trong thân <<EOF: {got!r}")
# Biến bị đổi mà các cách đọc khác không theo (bash 5.2 xoá đích ghi bên cạnh). Thân <<EOF không nháy: shell cha thay `$D`
# trong thân TRƯỚC khi shell con chạy, kể cả trong phạm vi lồng bên trong; phép gán trong thân không đổi được `$D` đó.
# read, mapfile, readarray, getopts, printf -v, local, for, eval, `.`: biến thành không biết; unset: rỗng. Phép gán trong một
# khâu của ống chạy ở shell con, sau `||` có thể không chạy: không biết.
for cmd in ("D=/; bash <<EOF\nD=/tmp/w && rm -rf $D/a\nEOF",             # xoá //a
            "D=/; bash <<EOF\nD=/tmp/w; rm -rf $D\nEOF", "D=/; sh <<EOF\nD=/tmp/w\nrm -rf ${D}\nEOF",  # xoá /
            "D=/; bash <<EOF\nbash <<'X'\nD=/tmp/w; rm -rf $D/a\nX\nEOF",  # xoá //a
            'D=/tmp/w; read D <<< /; rm -rf "$D"', 'D=/tmp/w; read -r D <<< /; rm -rf "$D"',  # xoá /
            'D=/tmp/w; mapfile -t D <<< /; rm -rf "$D"', 'D=/tmp/w; readarray -t D <<< /; rm -rf "$D"',
            'D=/tmp/w; printf -v D /; rm -rf "$D"', 'D=/tmp/w; while read D; do\nrm -rf "$D"\ndone <<< /',
            'D=/tmp/w; for D in /; do\nrm -rf "$D"\ndone',
            'D=/tmp/w; getopts a D; rm -rf "$D"',                          # xoá đúng tệp tên `?` ở thư mục dự án ("$D": không glob)
            'D=/tmp/w; f() { local D; rm -rf "$D/a"; }; f',                # xoá /a
            "D=/tmp/w; eval 'D=/'; rm -rf \"$D\"", "D=/tmp/w; printf 'D=/' > e.sh; . ./e.sh; rm -rf \"$D\"",  # xoá /
            "D=/tmp/w; unset D; rm -rf $D/a", "D=/tmp/w; unset -v D; rm -rf $D/a",  # xoá /a
            "export D=/tmp/w | rm -rf ${D}src", "D=/tmp/w | true; rm -rf ${D}src",  # xoá src
            "D=/; export D=/tmp/w | true; rm -rf $D", "D=/; true | D=/tmp/w; rm -rf $D",  # xoá /
            "D=/; true || D=/tmp/w; rm -rf $D"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"biến bị đổi mà cách đọc khác không theo: {cmd!r}: {got!r}")
check(not a.suspicious_labels("D=/tmp/w; unset -f D; rm -rf $D/a", a.SUSPICIOUS), "unset -f chỉ xoá hàm: biến giữ giá trị")
# Thân <<EOF không nháy có `\'` hay `$'…'`: chỉ cách đọc strict che đúng, các cách khác để nháy mở chuỗi nuốt dòng rm. `\$D`
# shell cha để nguyên cho shell con thay (D không export: rỗng); `$D` shell cha thay bằng giá trị tại toán tử heredoc, trước
# gán tạm và lệnh sau toán tử trên dòng mở, kể cả khi có thân -c gỡ ra ở giữa. Thân -c sau toán tử vẫn được gỡ (`+e` chỉ
# regex của strict nhận). Bash 5.2 xoá đích ghi bên cạnh (rm thay bằng echo).
for cmd in ("D=/tmp/w; bash <<EOF\necho it\\'s\nrm -rf \\$D/a\necho 'x'\nEOF",                # xoá /a
            "D=/tmp/w; bash <<EOF\nprintf $'a\\'b\\n'\nrm -rf \\$D/a\necho 'x'\nEOF",        # xoá /a
            "D=/; bash <<EOF; D=/tmp/w\necho it\\'s\nrm -rf $D/x\necho 'x'\nEOF",           # xoá //x
            "D=/; D=/tmp/w bash <<EOF\necho it\\'s\nrm -rf $D/x\necho 'x'\nEOF",            # xoá //x
            "D=/; bash <<EOF; D=/tmp/w\nprintf $'a\\'b\\n'\nrm -rf $D/x\necho 'x'\nEOF",    # xoá //x
            "D=/; bash <<EOF && D=/tmp/w\necho it\\'s\nrm -rf $D/x\necho 'x'\nEOF",         # xoá //x
            "D=/; bash <<EOF; bash +e -c 'true'; D=/tmp/w\necho it\\'s\nrm -rf $D/x\necho 'x'\nEOF",  # xoá //x
            "bash <<EOF +e -c 'rm -rf /'; true\necho it\\'s\nEOF"):                         # xoá /
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"thân <<EOF: `\\$` là của shell con, env của shell cha chụp tại toán tử: {cmd!r}: {got!r}")
# Cùng lớp khi biến là cờ hay tên lệnh (reviewer chặn vòng 3; mọi bản trước trả []): bản so mẫu cũng phải thay `$X` bằng giá
# trị tại toán tử, và `\$X` bằng env của shell con (gán trong thân) sau khi bỏ `\`. Bash 5.2 chạy `rm -rf /x`.
for cmd in ("O=-rf; bash <<EOF; O=-f\necho it\\'s\nrm $O /x\necho 'x'\nEOF",        # cờ, gán sau toán tử
            "O=-rf; O=-f bash <<EOF\necho it\\'s\nrm $O /x\necho 'x'\nEOF",         # cờ, gán tạm
            "C=rm; bash <<EOF; C=echo\necho it\\'s\n$C -rf /x\necho 'x'\nEOF",      # tên lệnh, gán sau toán tử
            "C=rm; C=echo bash <<EOF\necho it\\'s\n$C -rf /x\necho 'x'\nEOF",       # tên lệnh, gán tạm
            "C=echo; bash <<EOF\necho it\\'s\nC=rm; \\$C -rf /x\necho 'x'\nEOF",   # `\$`: shell con thay
            "O=-f; bash <<EOF\nO=-rf; rm \\$O /x\nEOF"):                              # `\$`, không mẹo nháy
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"thân <<EOF: biến là cờ hay tên lệnh: {cmd!r}: {got!r}")
# Cả lớp đó (lưới dùng chung với oracle bash của PR #8, nơi bash thật kiểm mô hình của lưới): mọi lệnh nguy phải vào A.
spec = importlib.util.spec_from_file_location("heredoc_grid", sys.argv[16])
hg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hg)
grid = [(c, why) for c, danger, why in hg.heredoc_grid() if danger]
missed = [(len(c), c, why) for c, why in grid if "xoá đệ quy" not in a.suspicious_labels(c, a.SUSPICIOUS)]
check(len(grid) >= 800 and not missed, f"lưới thân <<EOF ({len(grid)} lệnh nguy): mục A bỏ sót {len(missed)}, ngắn nhất: "
      + "; ".join(f"{why}: {c!r}" for _n, c, why in sorted(missed)[:5]))
# Thư mục cd không biết: cd ngay sau `||` chỉ chạy khi lệnh trước lỗi, sau `|` chạy ở shell con (bash chạy rm ở thư mục dự
# án). Đích còn `$` hay lệnh lồng sau khi thay biến đã biết có thể là đường tuyệt đối: cd vào thư mục tạm không làm nó vô hại
# (D chưa gán, `echo` in rỗng: bash xoá /a).
for cmd in ("D=/tmp/w || cd /tmp/w && rm -rf src", "D=/tmp/w || cd /tmp && rm -rf src", "true | cd /tmp && rm -rf src",
            "cd /tmp && rm -rf $D/a", "cd /tmp && rm -rf ${D}/a", "cd /tmp && rm -rf `echo`/a", "cd /tmp && rm -rf $(echo)/a"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"không biết thư mục hay đích sau cd: {cmd!r}: {got!r}")
check(not a.suspicious_labels("cd /tmp && rm -rf src", a.SUSPICIOUS), "cd vào thư mục tạm rồi xoá đích tương đối vẫn vô hại")
# Lệnh bash thật xoá đích nguy hiểm mà mục A từng bỏ sót (MISSED_VP, oracle bash của nhánh vibrant-pascal tìm ra): mục A phải
# nghi. MISSED_VP_PENDING là chỉ số các ca còn bỏ sót, chỉ được GIẢM: ca trong đó mà đã nghi cũng đỏ, để bỏ chỉ số ra và từ đó
# có assert canh. Chú thích mỗi dòng: việc sẽ che các ca đó (kế hoạch port vibrant-pascal).
spec = importlib.util.spec_from_file_location("missed_vp", sys.argv[14])
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)
MISSED_VP_PENDING = set()  # P2 (heredoc như bash, cách đọc bash) và P3 (cách đọc pure) đã nghi mọi ca
for i, (cmd, why) in enumerate(vp.MISSED_VP):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    if i in MISSED_VP_PENDING:
        check("xoá đệ quy" not in got, f"MISSED_VP[{i}] nay đã nghi: bỏ {i} khỏi MISSED_VP_PENDING để có assert canh: {cmd!r}")
    else:
        check("xoá đệ quy" in got, f"MISSED_VP[{i}] {why}: {cmd!r}: {got!r}")
# Glob mở bằng `.` (`.?`, `.[.]`, `.*`) khớp cả `..` ở bash < 5.2 (chưa có globskipdots; /bin/bash của macOS là 3.2): đích
# tương đối sau cd vào thư mục tạm hay build ra ngoài thư mục đó (bash 5.2 với `shopt -u globskipdots`, rm thay bằng echo:
# xoá ../../home tức /home, ../src của dự án).
for cmd in ("cd /tmp/x && rm -rf .?/.?/home", "cd /tmp/x && rm -rf .[.]/.[.]/home", "cd /tmp/x && rm -rf .*/.*/home",
            "cd dist && rm -rf .*/src"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"glob khớp `..` (bash < 5.2): ra ngoài thư mục cd: {cmd!r}: {got!r}")
check(not a.suspicious_labels("cd /tmp/x && rm -rf *.o", a.SUSPICIOUS),
      "glob không mở bằng `.` không khớp `..`: `*.o` sau cd vào thư mục tạm vẫn vô hại")
# Vòng kéo dòng của keep_shell_heredocs (`\` lẻ cuối dòng mở heredoc kéo dòng kế của thân vào lệnh) viết lại tuyến tính
# (5243b61 của nhánh chính; f8c96d5 của nhánh này làm cùng việc): đầu ra phải y như bản bậc hai ở mọi tổ hợp join, scoped,
# raw_marks, empty_body, exact, snap, strict, trên lệnh fixture, MISSED_VP, fuzz_vp_b/c và một lô riêng có `\` chẵn/lẻ cuối
# dòng mở và cuối các dòng thân. Bản tham chiếu: keep_shell_heredocs của nhánh chính (ca8b719) nguyên văn, chỉ thêm `a.`,
# đếm dòng kéo, chọn HEREDOC_STRICT khi strict, và thay vòng kéo dòng bằng vòng bậc hai của trước 5243b61.
import glob, itertools
pulled = []
def keep_shell_heredocs_ref(cmd, join=False, scoped=True, raw_marks=False, empty_body=True, exact=False, snap=False,
                            strict=False):
    def sub(m):
        line_start = m.string.rfind("\n", 0, m.start()) + 1
        while exact and line_start:
            prev_start = m.string.rfind("\n", 0, line_start - 1) + 1
            prev = m.string[prev_start:line_start - 1]
            if (len(prev) - len(prev.rstrip("\\"))) % 2 == 0:
                break
            line_start = prev_start
        rest, body, n = m["rest"], m["body"] or "", 0
        while scoped and join and body and re.search(r"(?<!\\)(\\\\)*\\$", rest):
            line, _, body = body.partition("\n")
            rest = rest[:-1] + line
            n += 1
        pulled.append(n)
        lead = m.string[line_start:m.start()]
        fed = a.SHELL_WORD.search(a.LINE_JOIN.sub(r"\1", lead) if exact else lead) or a.PIPE_SHELL.match(rest)
        if not (fed and scoped):
            return rest + "\n" + (body + "\n" if fed else "")
        mark = a.SNAP if snap and not raw_marks else ""
        return "\n".join((mark + rest, (a.OPEN_RAW if m["q"] else a.OPEN) + (a.NOT_LAST if rest.strip() else ""), body, a.CLOSE, ""))
    if scoped and not raw_marks:
        cmd = re.sub("[" + a.OPEN + a.OPEN_RAW + a.CLOSE + a.NOT_LAST + a.SNAP + "]", "�", cmd)
    return (a.HEREDOC_STRICT if strict else a.HEREDOC if scoped and empty_body else a.HEREDOC_6F32D5A).sub(sub, cmd)
def tool_commands(x):
    if isinstance(x, list):
        for v in x:
            yield from tool_commands(v)
    elif isinstance(x, dict):
        if x.get("type") == "tool_use" and isinstance(x.get("input"), dict) and isinstance(x["input"].get("command"), str):
            yield x["input"]["command"]
        for v in x.values():
            yield from tool_commands(v)
corpus = [c for c, _why in vp.MISSED_VP] + vp.fuzz_vp_b() + vp.fuzz_vp_c()
for f in glob.glob(os.path.join(sys.argv[15], "**", "*.jsonl"), recursive=True):
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try:
                corpus += tool_commands(json.loads(line))
            except ValueError:
                pass  # dòng hỏng có chủ ý của fixture
HD_OPEN = ["cat <<E", "cat <<'E'", "bash <<E", "bash <<'EOF'", "cat <<-E", 'sh <<"E"', "cat <<E | bash", "cd x <<'E'",
           "cat <<E; rm -rf src", "cat << E", "x <<A <<B"]
HD_TAIL = ["", "", "\\", "\\\\", "\\\\\\", " \\", "\\\\\\\\", "\\\\\\\\\\"]
HD_LINE = ["", "x", "rm -rf src", "| bash", "E", "EOF", " E", "\tE", "A", "B", "cd /tmp/x &&", "\\", "\\\\", "a\\\\\\", "cat <<E"]
rnd_hd = random.Random(7)
def heredoc_lines():
    out = [rnd_hd.choice(["", "D=/; ", "cd /tmp/x && ", "x \\\n"]) + rnd_hd.choice(HD_OPEN) + rnd_hd.choice(HD_TAIL)]
    out += [rnd_hd.choice(HD_LINE) + rnd_hd.choice(HD_TAIL) for _ in range(rnd_hd.randint(0, 6))]
    return "\n".join(out) + rnd_hd.choice(["", "\n", "\nrm -rf src", "\n\n", "\n\\", "\\"])
corpus += ["\n".join(heredoc_lines() for _ in range(rnd_hd.randint(1, 3))) for _ in range(3000)]
keep_diff = [(combo, c) for c in dict.fromkeys(corpus) for combo in itertools.product((False, True), repeat=7)
             if a.keep_shell_heredocs(c, *combo) != keep_shell_heredocs_ref(c, *combo)]
check(not keep_diff, f"keep_shell_heredocs khác bản bậc hai ở {len(keep_diff)} cặp (join, scoped, raw_marks, empty_body, "
                     f"exact, snap, strict), lệnh: {keep_diff[:3]}")
many = (sum(n > 0 for n in pulled), sum(n > 2 for n in pulled))
check(many[0] > 1000 and many[1] > 100, f"lô so keep_shell_heredocs phải đi qua vòng kéo dòng (lần kéo 1+, 3+ dòng): {many}")
# Bản bậc hai mất 3–15 giây với các chuỗi dưới đây (dò regex trên dòng mở dài dần, nối từng dòng).
slow = []
for cmd in ("cat <<E\\\n" * 3000, "bash <<E\\\n" * 5000, "sh <<'E' \\\n" * 5000, "cat <<E\\\\\\\n" * 5000,
            "cat <<E\\\n" + "x\\\\\\\n" * 10000):
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:16], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên dòng mở heredoc có `\\` lẻ cuối kéo nhiều dòng (đầu lệnh, giây): {slow}")
# Phần mới của cách đọc strict không làm audit chậm. Cỡ chuỗi chọn để 16e4dbd (chưa có strict) chạy dưới 1 giây: dòng mở
# heredoc không `\n` thì HEREDOC của các cách đọc khác thử lại từ mỗi `<<` rồi quét tới cuối dòng, bậc hai sẵn từ trước
# (~3 giây với 5000 `<<A`).
slow = []
for cmd in ("\\'" * 20000, "echo \\' " * 10000, "cat <<EOF\n" * 5000, "cat <<'EOF'\nEOF\n" * 3000, "<<A " * 2000,
            "D=/; bash <<EOF\n" * 2000, "read D; " * 3000, "printf -v D x; " * 3000, "unset D; " * 3000, "eval x; " * 3000,
            "D=1 | " * 3000, "x | " * 5000, "a || cd /tmp && " * 2000):
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:16], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên chuỗi `\\'`, heredoc, lệnh gán biến, ống (đầu lệnh, giây): {slow}")
# Tên biến dính liền redirection (`read D<<</etc`, `mapfile -t D</f`), trong nháy (`printf -v "D"`, `unset 'D'`) hay trong cờ
# gộp (`printf -vD`): bash 5.2 vẫn gán (rm thay bằng echo, đích ghi bên cạnh; D đọc từ tệp là không biết).
for cmd in ('D=/tmp/w; read D<<</etc; rm -rf "$D"', 'D=/tmp/w; read D<<<"/etc"; rm -rf "$D"',  # xoá /etc
            'D=/tmp/w; read -r D<f; rm -rf "$D"', 'D=/tmp/w; mapfile -t D</f; rm -rf "$D"',
            'D=/tmp/w; printf -vD /etc; rm -rf "$D"', 'D=/tmp/w; printf -v "D" /etc; rm -rf "$D"',  # xoá /etc
            "D=/tmp/w; unset 'D'; rm -rf $D/a", 'D=/tmp/w; unset -v "D"; rm -rf $D/a'):  # xoá /a
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"tên biến dính redirection, trong nháy, trong cờ gộp: {cmd!r}: {got!r}")
check(not a.suspicious_labels("D=/tmp/w; unset -f 'D'; rm -rf $D/a", a.SUSPICIOUS), "unset -f 'D' chỉ xoá hàm: biến giữ giá trị")
# Thân -c dạng nháy ANSI-C `$'…'` vẫn là lệnh: bash 5.2 xoá / hay .. (rm thay bằng echo).
for cmd in ("bash +e -c $'rm -rf /'", "bash --rcfile /dev/null -c $'rm -rf /'", "bash -o pipefail -c $'rm -rf /'",
            "bash -o 'pipefail' -c $'rm -rf ..'"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"thân -c dạng nháy ANSI-C `$'…'` vẫn là lệnh: {cmd!r}: {got!r}")
# Nháy ANSI-C `$'…'` ngoài thân -c: `\'` bên trong là nháy thoát, không đóng chuỗi (bash 5.2 xoá src, x ở thư mục dự án).
cmd = "echo $'it\\'s'; rm -rf src 'x'"
check("xoá đệ quy" in a.suspicious_labels(cmd, a.SUSPICIOUS), f"`\\'` trong `$'…'` không đóng chuỗi: {cmd!r}")
# Here-string `<<<` không mở heredoc: dòng sau là lệnh (bash xoá src).
for cmd in ("wc -w <<< hello\nrm -rf src", "cat <<< EOF\nrm -rf src", "grep x <<<EOF\nrm -rf src"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check("xoá đệ quy" in got, f"here-string `<<<` không nuốt các dòng sau làm thân heredoc: {cmd!r}: {got!r}")
for cmd in ("cat <<< hello", "cat <<'EOF'\nrm -rf src\nEOF"):
    check(not a.suspicious_labels(cmd, a.SUSPICIOUS), f"here-string, thân heredoc là dữ liệu: không nghi: {cmd!r}")
# `.` có gán tạm phía trước vẫn chạy tệp trong shell hiện tại, biến gán trong tệp ở lại (bash xoá /).
cmd = "printf 'D=/' > e.sh; D=/tmp/w; x=1 . ./e.sh; rm -rf \"$D\""
check("xoá đệ quy" in a.suspicious_labels(cmd, a.SUSPICIOUS), f"`.` sau gán tạm làm mọi biến thành không biết: {cmd!r}")
# Các sửa trên không làm audit chậm. Cỡ chuỗi chọn để ed94f03 chạy dưới 1 giây (`read D<<<x; ` dài hơn thì HEREDOC của các
# cách đọc khác, bậc hai sẵn từ trước, đã mất vài giây).
slow = []
for cmd in ("bash +e -c $'" + "\\'" * 20000, "echo $'" * 10000, "$'" + "\\" * 20000, "$'\\" * 10000, "bash -c $'" * 5000,
            "bash -o pipefail -c $'" * 3000, "read D<<<x; " * 1000, "printf -vD x; " * 3000, "unset 'D'; " * 3000,
            "cat <<< EOF\n" * 3000, "x=1 " * 5000 + ". x", "x=1 . ./e.sh; " * 2000):
    t = time.monotonic()
    a.suspicious_labels(cmd, a.SUSPICIOUS)
    t = time.monotonic() - t
    if t > 3:
        slow.append((cmd[:16], round(t, 1)))
check(not slow, f"suspicious_labels quá 3 giây trên chuỗi `$'`, here-string, tên biến dính redirection (đầu lệnh, giây): {slow}")
# Ca oracle bash tìm ra (KNOWN_MISSES của 9a32fb3). Đích ghi bên cạnh là đích bash 5.2 xoá thật (rm thay bằng stub),
# thư mục /tmp/w có, /tmp/nope không có. Các ca gần đó mà bash chỉ xoá trong thư mục tạm không được thành nghi.
MUST_FLAG = [
    # biến chưa gán ở đầu đích: bash thay bằng rỗng, đích thành tuyệt đối
    "cd /tmp/w && rm -rf $D/a",                                  # xoá /a
    "echo 'a b' && cd /tmp/w && sh -c 'rm -rf $D/a' # don't",     # xoá /a
    "cd /tmp && rm -rf $D/a",                                     # docs/viec-can-lam.md 2.2 ý 6: xoá /a
    # phép gán hay cd trong một khâu của ống chạy ở shell con, không tới khâu sau hay lệnh sau ống
    "unset D && D=/tmp/w/ | rm -rf ${D}src",                      # xoá src của dự án
    "D=/tmp/w/ | true; rm -rf ${D}src",                           # xoá src của dự án
    "rm -rf /tmp/w/x | cd /tmp/w && rm -rf src",                  # xoá src của dự án
    "export D=/tmp/w | rm -rf ${D}src",                           # docs/viec-can-lam.md 2.2 ý 6: xoá src của dự án
    # cách đọc chặt bỏ cả phép gán sau `&&`, cách đọc lỏng nhận phép gán trong ống: chỉ exact thấy D=/srv/ (53f3ff2 trả [])
    "D=/tmp/x/; true && D=/srv/; true | D=/tmp/x/; rm -rf ${D}src",  # xoá /srv/src
    # khâu ống đóng nhóm `( … )`: env trở về như lúc mở nhóm, không về env trong nhóm (chỉ exact thấy thân `bash \⏎<<EOF`)
    "D=/srv/; (true; D=/tmp/x/; true | true)\nbash \\\n<<EOF\nrm -rf ${D}src\nEOF",  # xoá /srv/src
    # đoạn sau `||` ở cách đọc chặt không gán gì: biến giữ giá trị cũ, không thành chưa biết
    "C=rm; true || C=echo\nbash \\\n<<EOF\n$C -rf /\nEOF",              # chạy rm -rf /
    # thân heredoc rỗng: dòng EOF ngay sau dòng mở là dấu đóng, lệnh sau nó là lệnh
    ": <<'EOF'\nEOF\nbash <<EOF\nrm -rf src # don't",             # xoá src của dự án
    "cat <<'EOF'\nEOF\nbash -c 'cd /tmp/w && rm -rf src'; bash -c \"rm -rf $D/a\"",  # xoá /a
    "cat <<'EOF'\nEOF\nrm -rf src", "cat <<-EOF\n\tEOF\nrm -rf src",  # xoá src của dự án
    # lệnh ngay sau || có thể không chạy: thư mục cd và biến gán ở đó không chắc có
    "cd / || cd /tmp/nope && rm -rf /tmp/w\\\n  src",             # cd / thành công, bỏ qua cd sau ||: xoá /src
    "true || cd /tmp/w && rm -rf src",                            # xoá src của dự án
    "true || D=/tmp/w/ && rm -rf ${D}src",                        # gán sau || không chạy: xoá src của dự án
    "D=/tmp/w || cd /tmp/w && rm -rf src",                        # docs/viec-can-lam.md 2.2 ý 6: xoá src của dự án
]
for cmd in MUST_FLAG:
    check(a.suspicious_labels(cmd, a.SUSPICIOUS), f"bash xoá đích ngoài thư mục tạm, mục A phải báo: {cmd!r}")
for cmd in (
    "D=src; cd /tmp/w && rm -rf $D",
    "D=/tmp/w/; echo x | cat; rm -rf ${D}src", "cd /tmp/w && rm -rf src | cat",
    "cat <<'EOF'\nEOF\nrm -rf node_modules",
    "cd /tmp/w && rm -rf src || true",
):
    check(not a.suspicious_labels(cmd, a.SUSPICIOUS), f"bash chỉ xoá trong thư mục tạm, không được thành nghi: {cmd!r}")
# `\` cuối mỗi dòng thân kéo dòng kế vào lệnh: kéo từng dòng không được tốn thời gian bậc hai theo số dòng. Bản bậc hai
# (trước b7ccd40) mất ~45 s với 40000 dòng, bản tuyến tính ~0,5 s (12 cách đọc; 20/10/2026: nhỏ nhất 0,51 s, trung vị 0,53 s
# qua 9 lần đo). Ngưỡng 5 s cách cả hai khoảng 9 lần, để máy CI chậm hơn không đỏ giả. Bash nối cả 40002 dòng thành lệnh
# mở, thân rỗng, rm chạy sau EOF.
import time
cmd = "cat <<'EOF' \\\n" + "x \\\n" * 40000 + "| bash\nEOF\nrm -rf src"
t0 = time.perf_counter()
got = a.suspicious_labels(cmd, a.SUSPICIOUS)
dt = time.perf_counter() - t0
check(dt < 5 and "xoá đệ quy" in got,
      f"40000 dòng `x \\` kéo vào dòng mở heredoc phải xong dưới 5 s, rm sau EOF vẫn nghi: {dt:.1f} s, {got!r}")
# Heredoc chưa đóng: bash đọc thân tới hết chuỗi (cảnh báo delimited by end-of-file), rm là dữ liệu của cat, không chạy.
got = a.suspicious_labels("cat > f <<'EOF'\nrm -rf src", a.SUSPICIOUS)
check(got == [], f"heredoc chưa đóng nuốt tới hết chuỗi như bash: {got!r}")
# Cách đọc như 6f32d5a (không nhận thân rỗng, thân tới hết chuỗi) vẫn ở trong phép hợp: chỉ nó thấy rm ở đây. `\` nối
# D=/tmp/x/ thành tham số của true nên D rỗng: bash xoá src và `\`. Guard hỏi lệnh này (vào H) nên gọi trực tiếp.
got = a.suspicious_labels("bash <<'EOF'\nEOF\ntrue \\\ncat <<'EOF' \\\nD=/tmp/x/; rm -rf ${D}src \\", a.SUSPICIOUS)
check("xoá đệ quy" in got, f"cách đọc như 6f32d5a (không nhận thân rỗng) vẫn ở trong phép hợp: {got!r}")
# cd nằm trong comment giữa đoạn không chạy, kể cả khi thân đưa vào `| bash` (chế độ không che nháy hay comment): oracle bash
# của blissful-dirac, bash xoá thư mục dự án. Guard hỏi lệnh này (`rm -rf .`) nên không vào A: kiểm thẳng.
cmd = "cat <<'EOF' | bash\n( : # x; cd /tmp/w &&\nrm -rf . )\nEOF"
check("xoá đệ quy" in a.suspicious_labels(cmd, a.SUSPICIOUS), f"cd trong comment không chạy: không biết thư mục: {cmd!r}")
# `#` không ở đầu từ (`$#`, `${#x}`, `a#b`, `a=#x`, sau `\ `) không mở comment: nháy sau nó mở chuỗi, bash không chạy rm.
for cmd in ("echo $# 'x\nrm -rf src\n'", "echo ${#x} 'x\nrm -rf src\n'", "echo a#b 'x\nrm -rf src\n'",
            "a=#x 'x\nrm -rf src\n'"):
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    check(got == [], f"`#` không ở đầu từ không mở comment, rm nằm trong chuỗi: {cmd!r}: {got!r}")
# Sau `\ ` (khoảng trắng đã thoát) cũng vậy, nhưng cách đọc exact (PR #5) coi `#` sau mọi khoảng trắng là comment nên báo
# thừa lệnh này: phép hợp có nhãn. Canh các cách đọc không exact, nơi cách che biết comment được thêm vào.
cmd = "echo x\\ # don't\nrm -rf src\n'"
got = [p for comments in (False, True) for scoped, pe in ((False, False), (True, False), (True, True)) for j in (False, True)
       for p, _f, _c, _s in a.segments(cmd, "Bash", j, scoped, pe, comments) if "rm" in p]
check(got == [], f"`#` sau `\\ ` không mở comment ở các cách đọc không exact, rm nằm trong chuỗi: {cmd!r}: {got!r}")
# `<<NAME` trên dòng cuối không có `\n` không mở được heredoc: mỗi lần thử không được quét lại cả dòng theo nhóm
# `(?:[^\n\\]|\\[^\n])*` (8ccdb8e), chậm hơn `[^\n]*` cỡ trăm lần. 20/10/2026 (4 nhân), dòng rm rồi 2000 lần `<<EOF `:
# b13bd51 37,3 s, f5bc021 0,74 s, bản có lookahead 0,47 s (trung vị 9 lần). Ngưỡng 4 s cách hai bản ~8–9 lần. Bash chạy rm ở
# dòng đầu rồi dừng ở dòng 2 (maximum here-document count exceeded).
cmd = "rm -rf src\n" + "<<EOF " * 2000
t0 = time.perf_counter()
got = a.suspicious_labels(cmd, a.SUSPICIOUS)
dt = time.perf_counter() - t0
check(dt < 4 and "xoá đệ quy" in got,
      f"2000 lần `<<EOF ` trên dòng không có `\\n` phải xong dưới 4 s, rm ở dòng trước vẫn nghi: {dt:.1f} s, {got!r}")
# expand không được chạy re.sub cho mọi biến của env ở mỗi đoạn: quá 512 tên khác nhau thì bộ đệm regex của `re` không giữ
# nổi, regex bị dịch lại mỗi lần. 20/10/2026 (4 nhân), 600 phép gán khác tên rồi rm: 0437c0b 69,9 s, bản bỏ qua tên vắng
# trong text 0,60 s (trung vị 9 lần). Ngưỡng 6 s cách hai bản ~10–12 lần. Bash xoá ./src.
cmd = "; ".join("V%d=/tmp/x" % i for i in range(600)) + "; rm -rf src"
t0 = time.perf_counter()
got = a.suspicious_labels(cmd, a.SUSPICIOUS)
dt = time.perf_counter() - t0
check(dt < 6 and "xoá đệ quy" in got, f"600 phép gán khác tên rồi rm phải xong dưới 6 s, rm vẫn nghi: {dt:.1f} s, {got!r}")
# Đoạn không có `$` thì expand không duyệt env. 21/10/2026 (4 nhân), trung vị 3 lần, 5000 biến (phép gán, hay unset mà cách
# đọc strict ghi thành rỗng) rồi 5000 đoạn `true`: b06eb79 4,6 và 2,7 s (31893fb, chưa có strict: 2,3 và 0,1 s), bản có lối
# tắt 0,27 và 0,29 s. Ngưỡng 1,5 s cách bản có lối tắt ~5 lần, b06eb79 ~2–3 lần. Bash không xoá gì.
for cmd in (" ".join("v%d=1" % i for i in range(5000)) + "; " + "true; " * 5000,
            "unset " + " ".join("v%d" % i for i in range(5000)) + "; " + "true; " * 5000):
    t0 = time.perf_counter()
    got = a.suspicious_labels(cmd, a.SUSPICIOUS)
    dt = time.perf_counter() - t0
    check(dt < 1.5 and got == [], f"5000 biến rồi 5000 đoạn không `$` phải xong dưới 1,5 s: {cmd[:12]!r}: {dt:.1f} s, {got!r}")
# Lệnh bật mọi chiều của phép hợp cách đọc (NAME=, byte dấu, heredoc thân rỗng) không được đọc lại cả lệnh theo từng tổ hợp
# khi các tổ hợp cho cùng kết quả. 21/10/2026 (4 nhân, Python 3.13), 1000 dòng không `$`, `#`, `\` rồi heredoc thân rỗng,
# byte \x01, `V=1 rm`, trung vị 5 lần: 38bf5bb 6,2 s (88 lần gọi segments), be281ef (thêm pipe_scope) 7,5 s (104 lần gọi),
# bản gộp tổ hợp trùng 0,40 s (7 lần gọi); e5a6756 xong 0,47 s nhưng bỏ sót rm (20/10). Ngưỡng 3 s cách bản gộp ~7,5 lần,
# be281ef ~2,5 lần. Bash xoá ./src.
cmd = "\n".join(['echo "x" | grep -c x && ls -la /home/user'] * 1000) + "\ncat > f <<'EOF'\nEOF\necho '\x01'\nV=1 rm -rf src"
t0 = time.perf_counter()
got = a.suspicious_labels(cmd, a.SUSPICIOUS)
dt = time.perf_counter() - t0
check(dt < 3 and got == ["xoá đệ quy"],
      f"1000 dòng rồi heredoc thân rỗng, byte \\x01, `V=1 rm` phải xong dưới 3 s, nhãn đúng ['xoá đệ quy']: {dt:.1f} s, {got!r}")
# Gộp tổ hợp đọc trùng (reading_key) không được đổi nhãn hay thứ tự nhãn: so với phép hợp đọc đủ mọi tổ hợp như 38bf5bb,
# gọi thẳng segments. Bỏ một điều kiện của reading_key thì lệnh ghi chú bên cạnh đổi nhãn, trừ vế OPEN_RAW của parent_env
# (assert mức đoạn ở dưới canh) và điều kiện raw_marks. raw_marks không lệnh nào canh được: các tổ hợp raw_marks khác nhau
# mà b có SNAP thì b đã khác (SNAP chèn chỉ khi raw_marks=False, khi đó byte có sẵn đã bị trung hoà). Bỏ parent_env khỏi
# khoá đệm b thì nhãn không đổi nhưng assert mức đoạn đỏ: SNAP đứng ngay trước `#` sau toán tử heredoc làm `#` thôi là
# comment, nháy trong đó mở chuỗi.
import re
def every_reading(cmd, tool="Bash"):
    joins = (True,) if tool == "PowerShell" else (False, True)
    marks = (False, True) if re.search("[\x01-\x05]", cmd) else (False,)
    stricts = (False, True) if re.search(r"(?:^|[\s;&|'\"])[A-Za-z_][A-Za-z0-9_]*=", cmd) else (False,)
    empties = (True, False) if any(m["body"] is None for m in a.HEREDOC.finditer(cmd)) else (True,)
    segs = [s for st in stricts for co in (False, True) for sc, pe in ((False, False), (True, False), (True, True))
            for rm in (marks if sc else (False,)) for eb in (empties if sc else (True,)) for j in joins
            for s in a.segments(cmd, tool, j, sc, pe, co, rm, st, eb)]
    if re.search(r"<<-?\s*[A-Za-z_]", cmd):
        segs += [s for j in joins for s in a.segments(cmd, tool, j, parent_env=True, blank=True)]
    segs += [s for st in stricts for rm in marks for eb in empties for j in joins
             for s in a.segments(cmd, tool, j, raw_marks=rm, strict_assign=st, empty_body=eb, exact=True)]
    if "|" in cmd:  # cách đọc pipe_scope của PR #8
        segs += [s for st in stricts for rm in marks for eb in empties for j in joins
                 for s in a.segments(cmd, tool, j, raw_marks=rm, strict_assign=st, empty_body=eb, exact=True,
                                     pipe_scope=True)]
    # cách đọc strict của nhánh tích hợp audit
    segs += [s for rm in marks for j in joins for s in a.segments(cmd, tool, j, raw_marks=rm, exact=True, strict=True)]
    if "$" in cmd:  # cách đọc pure (P3): biến chỉ đổi theo phép gán thuần
        segs += [s for rm in marks for j in joins
                 for s in a.segments(cmd, tool, j, raw_marks=rm, exact=True, strict=True, pure=True)]
    if "<<" in cmd:  # cách đọc bash (P2): heredoc và here-string như bash, với env của strict và của pure
        segs += [s for pu in ((False, True) if "$" in cmd else (False,)) for rm in marks for j in joins
                 for s in a.segments(cmd, tool, j, raw_marks=rm, exact=True, strict=True, pure=pu, bash=True)]
    ifs, labels = bool(re.search(r"\bIFS\b", cmd)), []
    for plain, full, ctx, subst in segs:
        for rx, label in a.SUSPICIOUS:
            if label in labels or not re.search(rx, plain, re.IGNORECASE):
                continue
            if label == "xoá đệ quy" and a.benign_delete(full, ctx, worktree=not (subst or ifs), tool=tool):
                continue
            if label == "xoá nhánh local (-D)" and a.AGENT_BRANCH_DELETE.search(a.TAIL_REDIRECT.sub("", full)):
                continue
            labels.append(label)
    return labels
REPS = [("Bash", c) for c in (
    "rm -rf dist\\\n  src",                                        # b có nối dòng
    "D=/tmp/w; bash -c 'D=/; rm -rf $D'",                          # b của exact có gỡ thân -c
    "echo x\\ # don't\nrm -rf src\n'",                             # exact khi b có `#`
    "cd /tmp/w && bash <<'EOF'\necho don't\nEOF\nrm -rf src 'x'",  # exact khi b có byte dấu
    "cd /tmp/x && \x01 x\\ # && rm -rf y",                         # scoped khi b có byte dấu
    "A=s; B=${A}h; cd /tmp/x && $B\nrm -rf y",                     # scoped khi b có `$` (ghép ra shell trơn)
    "cd /tmp/w && bash\nrm -rf src",                               # scoped khi b có "sh"
    "D=/tmp/x/; true && D=/srv/; true | D=/tmp/x/; rm -rf ${D}src",  # pipe_scope giữ nguyên trong lớp
    "echo >#'\nrm -rf src\n'",                                     # comments khi b có `#`
    "D=/tmp/x/ true; rm -rf ${D}src",                              # strict_assign khi b có `$`
    "D=/srv/\n\x02\nD=/tmp/x/\nrm -rf ${D}src",                    # parent_env khi b có `$` và dấu mở
    "D=/tmp/x; bash <<EOF\nrm -rf $D/src\nEOF",                    # blank khi b có `$` và dấu mở
    "bash <<'EOF'#'\nrm -rf src\nEOF\necho '\n",                    # parent_env trong khoá đệm b (SNAP trước `#`)
    "echo \"x\" | grep -c x && ls -la /home/user\ncat > f <<'EOF'\nEOF\necho '\x01'\nV=1 rm -rf src",
    "bash <<'EOF'\nEOF\ntrue \\\ncat <<'EOF' \\\nD=/tmp/x/; rm -rf ${D}src \\",
    "true | cd /tmp/x && rm -rf y #'\ncat <<'EOF' \\\n# don't $x\nEOF",
    "D=/tmp/x/; bash <<'A' <<'EOF'\nA\nrm -rf ${D}src\nEOF", "D=/tmp/x/; bash -s <<'EOF' \\\nEOF\nrm -rf ${D}src\nEOF",
    "bash <<EOF; D=/tmp/x\nrm -rf $D/src\nEOF", "D=/tmp/x; bash <<EOF -c 'D=$HOME/proj; rm -rf $D'\nEOF",
    "D=/tmp/y/; bash <<'EOF'\n\x01\nrm -rf ${D}src\nEOF", "bash \\\n<<'EOF'\n# x \\\nD=/; rm -rf $D\nEOF",
    "cat <<'EOF' | bash\n( : # x; cd /tmp/w &&\nrm -rf . )\nEOF", "git push --force origin main && rm -rf src; git reset --hard",
    "cd /tmp/x && rm -rf y", "rm -rf node_modules && rm -rf /tmp/build", "IFS=/; D=.claude/worktrees/agent-ab; rm -rf $D",
    "git -C .claude/worktrees/agent-a1b2c3d4e5f60718 status && git branch -D worktree-agent-a1b2c3d4e5f60718",
    # strict giữ nguyên trong lớp: cùng b với exact mà che nháy hay theo env khác (hai lệnh đầu), b khác (ba lệnh sau)
    "echo it\\'s\nrm -rf src 'x'", "D=/tmp/w; read D <<< /; rm -rf \"$D\"", "cat <<< EOF\nrm -rf src\nEOF",
    "D=/; bash <<EOF\nD=/tmp/w; rm -rf $D\nEOF", "bash -c - 'rm -rf /'",
)] + [("PowerShell", c) for c in (
    'Set-Location "C:\\vnstock\\"; Remove-Item -Recurse -Force data_warehouse\\prices', "cat <<'EOF' | bash\ngit stash drop\nEOF",
    "D=/tmp/y/; bash <<'EOF'\n\x01\nrm -rf ${D}src\nEOF", "rm -rf dist\\\n  src # don't",
    "bash +e -c 'rm -rf /'",  # strict của PowerShell: thân -c gỡ bằng regex mở rộng
)]
for tool, cmd in REPS:
    got, want = a.suspicious_labels(cmd, a.SUSPICIOUS, tool), every_reading(cmd, tool)
    check(got == want, f"gộp tổ hợp đọc trùng không được đổi nhãn hay thứ tự nhãn: {tool} {cmd!r}: {got!r}, đọc đủ: {want!r}")
# Mọi tổ hợp cùng lớp reading_key phải cho đúng cùng danh sách đoạn, không chỉ cùng nhãn: nhãn có thể còn nguyên chỉ nhờ
# cách đọc khác đọc thừa. Bỏ vế OPEN_RAW khỏi điều kiện parent_env thì REPS vẫn xanh, nhưng `D=/tmp/x/; bash <<'EOF'⏎rm -rf
# ${D}src⏎EOF` gộp tổ hợp cho `rm -rf /tmp/x/src` với tổ hợp cho `rm -rf src`. Canh cả lúc sửa segments mà quên reading_key:
# bước so với bản trước không thấy cách đọc mà bản trước chưa có. Lệnh sinh cố định (hạt 7) từ cấu trúc mà các chiều của
# phép hợp đọc khác nhau: biến, cd, heredoc mọi kiểu, byte dấu, comment, nháy lẻ, `\` cuối dòng, thân -c, ống, `||`, `&`.
import random
KTOK = ["rm -rf src", "rm -rf /tmp/x", "rm -rf $D", "rm -rf ${D}src", "D=/tmp/x/", "D=/", "D=/tmp/x/ true", "cd /tmp/x",
        "bash", "sh -s", "bash -c 'D=/; rm -rf $D'", 'sh -c "rm -rf $D"', "bash <<EOF", "bash <<'EOF'", "cat <<'EOF'",
        "cat <<EOF", "EOF", "<<'EOF'", "# x", "#'", "# don't", "don't", "'", '"', "\\", "\x01", "\x02", "\x03", "\x04", "\x05",
        "$B", "B=sh", "${A}sh", "echo x", "true", "(", ")", "{", "}", "&", "export D=/tmp/x", "| bash", "IFS=/", "s\\\nh",
        "$HOME", "x=$(", "-c", "--", "Set-Location /tmp/x", "Remove-Item -Recurse -Force src"]
KSEP = [" ", "\n", "; ", " && ", " || ", " | ", " \\\n", "\n", "\n"]
krnd = random.Random(7)
def kcmd():
    c = "".join(krnd.choice(KTOK) + krnd.choice(KSEP) for _ in range(krnd.randint(1, 9)))
    return c.rstrip(" ") if krnd.random() < 0.5 else c
clash = []
for tool, cmd in REPS + [(t, kcmd()) for t in ("Bash", "Bash", "PowerShell") for _ in range(500)]:
    bodies, seen = {}, {}
    for combo in a.reading_combos(cmd, tool):
        key, segs = a.reading_key(cmd, tool, combo, bodies), a.segments(cmd, tool, *combo)
        if seen.setdefault(key, (combo, segs))[1] != segs:
            clash.append((len(cmd), tool, cmd, seen[key][0], combo))
            break
check(not clash, f"reading_key gộp hai tổ hợp cho danh sách đoạn khác nhau ({len(clash)} lệnh), ngắn nhất: "
                 f"{sorted(clash)[:1]!r}")
# Trường pure (P3) của tổ hợp: lô riêng (hạt riêng, lô trên giữ nguyên) có cấu trúc mà cách đọc pure đọc khác strict: phép
# gán không thuần, lệnh ghép, thân hàm, subshell, local, unset, read, IFS, `\;`. Tổ hợp pure phải là một lớp riêng: gộp nó
# với tổ hợp strict thì danh sách đoạn khác (`D=/tmp/x; local D=/; rm -rf $D` cho `rm -rf /tmp/x` ở strict, `rm -rf $D` ở pure).
PTOK = ["D=/tmp/x", "D=/", "D=", "local D=/", "unset D", "unset -f D", "read -aD", "((D=0))", "D[0]=/", "echo D=/", "D=/ true",
        "if true", "then", "fi", "f() {", "function f {", "}", "f", "(", ")", "{", "IFS=/", "echo a\\", "export D",
        "rm -rf $D", "rm -rf ${D}src", "bash <<EOF", "EOF", "# x", "$(", "while false", "do", "done"]
prnd = random.Random(11)
def pcmd():
    return "".join(prnd.choice(PTOK) + prnd.choice(KSEP) for _ in range(prnd.randint(1, 9))) + "rm -rf $D/src"
pclash, pdiff = [], 0
for cmd in ["D=/tmp/x; local D=/; rm -rf $D"] + [pcmd() for _ in range(400)]:
    bodies, seen = {}, {}
    combos = a.reading_combos(cmd)
    for combo in combos:
        key, segs = a.reading_key(cmd, "Bash", combo, bodies), a.segments(cmd, "Bash", *combo)
        if seen.setdefault(key, (combo, segs))[1] != segs:
            pclash.append((len(cmd), cmd, seen[key][0], combo))
            break
    pdiff += any(c[11] and a.segments(cmd, "Bash", *c) != a.segments(cmd, "Bash", *(c[:11] + (False,) + c[12:]))
                 for c in combos)  # trường 11: pure
check(not pclash, f"reading_key gộp hai tổ hợp (trường pure) cho danh sách đoạn khác nhau ({len(pclash)} lệnh), ngắn nhất: "
                  f"{sorted(pclash)[:1]!r}")
check(pdiff >= 100, f"lô của trường pure phải có lệnh mà pure đọc khác strict (canh lô thật sự phủ trường mới): {pdiff}/401")
# Trường bash (P2) của tổ hợp: lô MISSED_VP và fuzz_vp_c (heredoc tên lạ, `<<` dịch bit, here-string). Gộp tổ hợp bash với
# tổ hợp strict thì danh sách đoạn khác (`cat <<E-X⏎D=/tmp/w⏎E-X⏎rm -rf $D/a`: thân là dữ liệu chỉ ở cách đọc bash).
bclash, bdiff = [], 0
bcmds = [c for c, _why in vp.MISSED_VP] + vp.fuzz_vp_c() + ["bash <<< 'rm -rf src'", "cat <<E-X\nD=/tmp/w\nE-X\nrm -rf $D/a"]
for cmd in bcmds:
    bodies, seen = {}, {}
    combos = a.reading_combos(cmd)
    for combo in combos:
        key, segs = a.reading_key(cmd, "Bash", combo, bodies), a.segments(cmd, "Bash", *combo)
        if seen.setdefault(key, (combo, segs))[1] != segs:
            bclash.append((len(cmd), cmd, seen[key][0], combo))
            break
    bdiff += any(c[12] and a.segments(cmd, "Bash", *c) != a.segments(cmd, "Bash", *(c[:12] + (False,) + c[13:]))
                 for c in combos)  # trường 12: bash
check(not bclash, f"reading_key gộp hai tổ hợp (trường bash) cho danh sách đoạn khác nhau ({len(bclash)} lệnh), ngắn nhất: "
                  f"{sorted(bclash)[:1]!r}")
check(bdiff >= 100, f"lô của trường bash phải có lệnh mà bash đọc khác strict (canh lô thật sự phủ trường mới): "
                    f"{bdiff}/{len(bcmds)}")
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
  "$py" -I -B - "$tmp/audit-base.py" "$tmp" "$ref ($why)" "$vp" <<'PYEOF' || status=1
import glob, importlib.util, json, os, random, sys
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding="utf-8")  # -I bỏ qua PYTHONIOENCODING
base_file, tmp, ref, vp_file = sys.argv[1:5]
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
# Lô phụ, bộ sinh riêng để lô trên giữ nguyên từng lệnh: thân bash -c/sh -c có biến, cd và lồng nhau, cờ gộp, `\` + xuống
# dòng giữa shell và `<<`, nháy lẻ trong comment hay trong thân heredoc.
SUB = ["bash -c 'D=/; rm -rf $D'", 'sh -c "cd /tmp/w && rm -rf src"', "D=/tmp/w", "D=/", "bash -lc 'x'",
       "bash -lc 'rm -rf $D/a'", "sh -c 'rm -rf $D/a'", 'bash -c "rm -rf \\$D/a"', 'bash -c "true; D=/tmp/w"',
       "bash -c 'D=/tmp/w'", "bash -c \"bash -c 'rm -rf $D'\"", "bash -c 'cd /tmp/w'", "rm -rf $D", "rm -rf ${D}src",
       "rm -rf src 'x'", "echo don't", "echo 'a b'"]
SUB_LINE = ["bash \\\n<<'EOF'", "bash \\\n  -s <<'EOF'", "bash <<'EOF'", "cat <<'EOF'", "EOF", "# don't", "# x \\"]
rnd2 = random.Random(2)
def line2():
    if rnd2.random() < 0.3:
        return rnd2.choice(SUB_LINE)
    s = rnd2.choice([" && ", "; ", " || ", " | "]).join(
        rnd2.choice(SUB if rnd2.random() < 0.6 else CORE + STEP) for _ in range(rnd2.randint(1, 3)))
    return s + rnd2.choice(TAIL)
fuzz += ["\n".join(line2() for _ in range(rnd2.randint(1, 5))) for _ in range(1000)]
# Lô thứ ba, bộ sinh riêng để hai lô trên giữ nguyên từng lệnh: shell -c với cờ `+`, cờ trước và sau cụm c, tên của -o trong
# nháy hay có `-`, --rcfile/--init-file kèm tham số, cụm c có o kèm tên.
PRE = ["+e", "-x", "-o pipefail", "-o 'pipefail'", "-o interactive-comments", "--rcfile /dev/null", "--init-file x",
       "--login", "+O extglob"]
BODY = ["'rm -rf $D/a'", "'D=/; rm -rf $D'", '"rm -rf \\$D/a"', "'cd /tmp/w && rm -rf src'", "'echo hi'"]
rnd3 = random.Random(3)
def line_shc():
    return (rnd3.choice(["D=/tmp/w; ", "cd /tmp/w && ", ""]) + rnd3.choice(["bash", "sh", "git-bash"])
            + "".join(" " + rnd3.choice(PRE) for _ in range(rnd3.randint(0, 2)))
            + " " + rnd3.choice(["-c", "-lc", "+c", "-co pipefail", "-ec"])
            + "".join(" " + rnd3.choice(["-x", "+e", "-o pipefail", "--"]) for _ in range(rnd3.randint(0, 2)))
            + " " + rnd3.choice(BODY) + rnd3.choice(["", "; rm -rf $D", " && rm -rf src"]))
fuzz += ["\n".join(line_shc() for _ in range(1 if rnd3.random() < 0.7 else 2)) for _ in range(600)]
# Lệnh lồng (`bash … -c "… sh -c '…'"`) mà sửa regex thân -c tại chỗ (0a8cd90) từng làm mất nhãn so với 1667825: cách đọc
# exact phải giữ regex thân -c của bản trước, regex mở rộng chỉ dùng ở cách đọc strict.
fuzz += [
    'BASH +c -x --rcfile x "cd /tmp/w && bash -ce \'rm -rf src\'"',
    'D=/tmp/w; bash -o "pipefail" -x-c -c -ce -o pipefail -o \'pipefail\' "D=/tmp/w; git-bash -xc \'echo hi\'; rm -rf \\$D" \'tail\'',
    'D=/tmp/w; dash +bash --norc --rcfile /dev/null -cO extglob -e +e "cd /tmp/w && bash -x -o pipefail -c \'rm -rf src\'"',
    'X=1 bash -o "pipefail" +x -C -cO extglob "true; D=/tmp/w; sh -xc \'echo hi\'; rm -rf \\$D" \'tail\'',
    'bash -oc pipefail -o pipefail -o pipefail "cd /tmp/w && sh -o pipefail -c \'rm -rf \\$D/a\'"',
    'cd /tmp/w && bash -o interactive-comments -c -x "D=/tmp/w; git-bash -co \'pipefail\' -o pipefail \'echo hi\'; rm -rf \\$D" \'tail\'',
    'cd /tmp/w && bash.exe -co pipefail "cd /tmp/w && sh -ec \'rm -rf $D/a\'"',
    "cd /tmp/w && dash -co 'pipefail' 'rm -rf src' | bash",
    'cd /tmp/w && x-bash -co \'pipefail\' "D=/tmp/w; bash -ec \'echo hi\'; rm -rf \\$D"\nD=/; bash.exe -i --rcfile /dev/null +ec - -o \'pipefail\' "D=/tmp/w" \'tail\'',
    'cd /tmp/w && x-bash -o bash +c "D=/tmp/w; sh -co \'pipefail\' \'echo hi\'; rm -rf \\$D"',
    'cd /tmp/w && zsh -co \'pipefail\' +O extglob "rm -rf \\$D/a" | bash',
    'git-bash --init-file x -xc "cd /tmp/w && bash -o pipefail -o pipefail -cl \'rm -rf $D/a\'" \'tail\'',
    'bash +O extglob -c -o pipefail -x "cd /tmp/w && bash +O extglob -c \'rm -rf \\$D/a\'"',
    'bash -lc -o pipefail -o pipefail "cd /tmp/w && sh -ec \'rm -rf \\$D/a\'"',
    'bash -o \'pipefail\' -o pipefail -ec +e -o pipefail "cd /tmp/w && bash -x -ec \'rm -rf \\$D/a\'"\nbash --init-file x -co pipefail -- -- "rm -rf \\$D/a"',
    'cd /tmp/w && bash +O extglob --init-file x -ec "cd /tmp/w && bash +O extglob -o pipefail -c \'rm -rf \\$D/a\'"\ncd /tmp/w && sh -o \'pipefail\' -c \'rm -rf $D/a\'',
    'cd /tmp/w && bash +c "cd /tmp/w && bash -o pipefail -o pipefail -ec -- \'rm -rf \\$D/a\'"',
    'cd /tmp/w && bash -ec -x "sh -ec \'rm -rf \\$D/a\'"',
    'cd /tmp/w && git-bash +c "cd /tmp/w && sh -ec \'rm -rf \\$D/a\'"',
    'cd /tmp/w && git-bash --init-file x -lc -o pipefail -o pipefail "cd /tmp/w && bash -x -ec \'rm -rf \\$D/a\'"',
    'cd /tmp/w && git-bash -ec -x -o pipefail "D=/tmp/w; bash +O extglob +O extglob -c \'cd /tmp/w && rm -rf src\'; rm -rf \\$D"',
    'cd /tmp/w && sh +c -o pipefail +e "D=/tmp/w; git-bash --login -lc -- \'cd /tmp/w && rm -rf src\'; rm -rf \\$D"',
    'cd /tmp/w && sh --rcfile /dev/null -x -ec -x "D=/tmp/w; git-bash -lc \'echo hi\'; rm -rf \\$D"',
    'sh +c +e -x "D=/tmp/w; bash +O extglob -ec \'cd /tmp/w && rm -rf src\'; rm -rf \\$D"',
    'sh --init-file x -lc "D=/tmp/w; sh -lc \'echo hi\'; rm -rf \\$D"',
]
# Lô thứ tư, bộ sinh riêng để các lô trên giữ nguyên từng lệnh: mảnh của các chỗ cách đọc strict đọc khác (`\'`, `\"` ngoài
# nháy, `$'…'`, thân <<EOF không nháy đưa vào bash/sh, read/mapfile/printf -v/unset/eval/`.` kể cả tên dính redirection hay
# trong nháy, thân heredoc rỗng, here-string, `||`/`|` trước cd hay phép gán, `$D` chưa gán sau cd) ghép với lõi nguy hiểm
# và các bước có sẵn.
FRAG = ["echo it\\'s", 'echo a\\"b', "read D <<< /", "mapfile -t D <<< /", "printf -v D /", "unset D", "unset -f D",
        "eval 'D=/'", ". ./e.sh", "D=/tmp/w", "D=/", "export D=/tmp/w", "cd /tmp", "cd /tmp/w", "true", "false",
        "rm -rf $D/a", "rm -rf ${D}src", 'rm -rf "$D"', "rm -rf src 'x'", 'rm -rf src "x"',
        "read D<<</etc", 'read D<<<"/etc"', "read -r D<f", "mapfile -t D</f", "printf -vD /etc", 'printf -v "D" /etc',
        "unset 'D'", 'unset -v "D"', "unset -f 'D'", "x=1 . ./e.sh", "echo $'it\\'s'", "bash +e -c $'rm -rf $D/a'",
        "bash -o 'pipefail' -c $'D=/; rm -rf $D'"]
FRAG_LINE = ["bash <<EOF", "sh <<EOF", "bash <<'EOF'", "cat <<'EOF'", "cat <<EOF", "EOF", "EOF", "cat <<< EOF",
             "wc -w <<< hello"]
rnd4 = random.Random(4)
def line_strict():
    if rnd4.random() < 0.3:
        return rnd4.choice(FRAG_LINE)
    s = rnd4.choice(FRAG + CORE)
    for _ in range(rnd4.randint(0, 2)):
        s += rnd4.choice([" && ", "; ", " || ", " | "]) + rnd4.choice(FRAG + CORE + STEP)
    return s + rnd4.choice(TAIL)
fuzz += ["\n".join(line_strict() for _ in range(rnd4.randint(1, 5))) for _ in range(600)]
# Lệnh thêm (3000 lệnh trên giữ nguyên): một lõi chỉ nguy hiểm tuỳ cách đọc (biến, thư mục cd) giữa 0–4 dòng ngữ cảnh ghép
# từ cấu trúc mà từng cách đọc trong phép hợp của suspicious_labels được thêm vào để bắt: heredoc thân rỗng, `\`/`\\` cuối
# dòng mở rồi EOF, hai heredoc một dòng, <<EOF có biến trong thân, gán trước toán tử, gán sau `&&` có chạy, byte dấu, comment
# có nháy, `"cd"`, `&`, `$'\x63d'`. Lõi nguy hiểm ở mọi cách đọc (như CORE) che mất cách đọc riêng lẻ. Bỏ một giá trị của một
# chiều trong phép hợp (stricts, comments, scoped/parent_env, marks, empties, joins), kể cả cách đọc gốc như
# strict_assign=False, thì bước này phải đỏ khi so với bản còn giá trị đó; riêng raw_marks=False chỉ nhờ lệnh fixture có byte
# \x01–\x04. Chỉ Bash: đủ mọi chiều, đỡ thời gian.
NCORE = ["rm -rf ${D}src", "rm -rf $D/src", "rm -rf y"]
NSTEP = ["D=/tmp/x/", "export D=/tmp/x/", "D=/tmp/x/ | true", "false && D=/tmp/x/", "D=/tmp/x/ true", "echo D=/tmp/x/",
         "D=/srv/", "cd /tmp/x", '"cd" /home/p', "$'\\x63d' /home/p", "true", "echo 'a b'", "echo '\x01'"]
NLINE = ["bash <<'EOF'", "bash <<EOF", "bash <<'EOF'\nEOF", "cat > f <<'EOF'\nEOF", "bash -s <<'EOF' \\\nEOF",
         "cat > f <<'EOF' \\\\\nEOF", "bash <<'A' <<'EOF'\nA", "A", "EOF", "\x01", "\x02", "\x03", "# don't", "echo 'x",
         "D=/tmp/x/\nbash <<'EOF'\nEOF", "D=/tmp/x/; bash <<'A' <<'EOF'\nA", "bash <<'EOF'\nD=/srv/\nEOF", "bash <<EOF\nD=/tmp/x/",
         "D=/tmp/x/\n\x01", "D=/tmp/x/\ntrue && D=/srv/"]
NTAIL = ["", "", "", " \\", " \\\\", " # don't", " &"]
NSEP = [" && ", "; ", " || ", " | ", " & "]
def line3():
    if rnd.random() < 0.4:
        return rnd.choice(NLINE)
    s = rnd.choice(NSEP).join(rnd.choice(NSTEP) for _ in range(rnd.randint(1, 2)))
    return ("(" + s + ")" if rnd.random() < 0.05 else s) + rnd.choice(NTAIL)
def cmd3():
    ls = [line3() for _ in range(rnd.randint(0, 4))]
    ls.insert(rnd.randint(0, len(ls)), rnd.choice(["", "cd /tmp/x && "]) + rnd.choice(NCORE) + rnd.choice(NTAIL))
    return "\n".join(ls)
fuzz_bash = [cmd3() for _ in range(2000)]
pairs = list(dict.fromkeys(fixture + [(tool, c) for c in fuzz for tool in ("Bash", "PowerShell")]
                           + [("Bash", c) for c in fuzz_bash]))
# Lô của nhánh vibrant-pascal (fuzz_vp_b, fuzz_vp_c, bộ sinh riêng trong $vp) và các ca MISSED_VP: chỉ Bash, như oracle bash
# của nhánh đó.
vp = load("missed_vp", vp_file)
pairs = list(dict.fromkeys(pairs + [("Bash", c) for c in vp.fuzz_vp_b() + vp.fuzz_vp_c() + [c for c, _why in vp.MISSED_VP]]))
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

# Oracle bash: đối chiếu mục A với chính bash. Lớp lỗi "segments() đọc sai cấu trúc shell nên mục A bỏ sót lệnh xoá" đã cần
# hơn 10 commit fix(audit) (nối dòng, `--`, cd, heredoc, nháy lẻ trong comment, bash -c…), và phép so nhãn ở trên không thấy
# lỗi mà bản trước và bản này cùng có. Bước này chạy một bộ lệnh fuzz cố định bằng bash thật, `rm` thay bằng stub chỉ ghi
# thư mục và đích, rồi đỏ khi bash xoá đích nằm ngoài thư mục tạm mà suspicious_labels trả []. An toàn: stub là đường dẫn
# tuyệt đối ghi ngay trong văn bản lệnh (không đặt trên PATH: `bash -l` có thể đặt lại PATH), lệnh có git, push, reset, clean,
# Remove-Item hay `>` bị bỏ hẳn, cwd là thư mục tạm ngoài mọi repo git, HOME không tồn tại, stdin là /dev/null, có timeout.
# Chỉ chạy trong repo kit (như phép so nhãn) và với bash 5+ ngoài Windows: KNOWN_MISSES lập trên bash 5.2 và 5.3, sh là dash.
# Bản trước (cùng ref với phép so nhãn) dùng để canh KNOWN_MISSES chỉ được giảm; dòng ✔ ghi đã canh với bản nào hay vì sao
# bỏ qua.
if [ ! -f scripts/install-kit.sh ]; then
  printf '• audit: bỏ qua oracle bash (chỉ chạy trong repo kit)\n'
else
  base_test="" base_why="$skip$miss"
  if [ -z "$base_why" ]; then
    if git show "$ref:./scripts/test-audit.sh" >"$tmp/test-audit-base.sh" 2>/dev/null; then
      base_test="$tmp/test-audit-base.sh" base_why="$ref ($why)"
    else
      base_why="không có scripts/test-audit.sh ở $ref"
    fi
  fi
  "$py" -I -B - "$tmp/oracle-pr8" "$base_test" "$base_why" "$grid" <<'PYEOF' || status=1
import ast, glob, importlib.util, os, random, re, shutil, signal, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding="utf-8")  # -I bỏ qua PYTHONIOENCODING
root, base_test, base_why, grid_file = sys.argv[1:5]
# Lệnh bash xoá đích ngoài thư mục tạm mà mục A vẫn bỏ sót, có từ trước bước này: (lệnh, "lý do"). Sửa được ca nào thì xoá
# ca đó (bước này đỏ khi một ca đã hết sót mà còn nằm đây). Chỉ được giảm: thêm ca so với bản trước là đỏ, ca sót mới phải sửa.
KNOWN_MISSES = [
]
t0 = time.monotonic()
spec = importlib.util.spec_from_file_location("audit", "scripts/audit-agent.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
fails = []
known = dict(KNOWN_MISSES)
ratchet = f"bỏ qua: {base_why}"
# Dòng đầu của bước này. Oracle bash của blissful-dirac (bước kế) cũng mở bằng "# Oracle bash:" mà không có KNOWN_MISSES.
MARK = "# Oracle bash: đối chiếu mục A với chính bash."
if base_test:
    text = open(base_test, encoding="utf-8").read()
    before = None
    if MARK not in text and not re.search(r"^KNOWN_MISSES\b", text, re.M):
        ratchet = f"bản ở {base_why} chưa có bước oracle"
    else:  # đọc phép gán ở cột 0 trong khối Python chứa nó, dạng gì cũng được (`[]`, comment sau `]`…). Không đọc được, kể
        # cả khi tên bị đổi hay phép gán bị thụt vào, thì đỏ: bỏ qua chỉ khi bản trước chưa có bước này
        try:
            i = text.index("\nKNOWN_MISSES")
            i = text.index("\n", text.rindex("<<'PYEOF'", 0, i)) + 1
            node = next(n.value for n in ast.parse(text[i:text.index("\nPYEOF\n", i)]).body if isinstance(n, ast.Assign)
                        and [getattr(t, "id", "") for t in n.targets] == ["KNOWN_MISSES"])
            before = {c for c, _why in ast.literal_eval(node)}
            ratchet = f"so với bản ở {base_why}"
        except Exception as exc:
            fails.append(f"không đọc được KNOWN_MISSES của bản ở {base_why}: {exc!r}")
    added = [] if before is None else [c for c in known if c not in before]
    if added:
        fails.append(f"KNOWN_MISSES chỉ được giảm: thêm {len(added)} ca so với bản ở {base_why}: "
                     + "; ".join(repr(c) for c in added) + ". Sửa audit-agent.py cho ca đó, đừng ghi thêm.")
for c in known:
    labels = a.suspicious_labels(c, a.SUSPICIOUS)
    if labels:
        fails.append(f"ca trong KNOWN_MISSES đã hết sót (mục A báo {', '.join(labels)}): xoá nó khỏi danh sách: {c!r}")

def finish(note):
    for f in fails:
        print("✘ audit: oracle bash:", f, file=sys.stderr)
    if note:
        print(note)
    sys.exit(1 if fails else 0)

bash = shutil.which("bash")
if os.name != "posix" or sys.platform.startswith(("cygwin", "msys")):
    finish("• audit: bỏ qua oracle bash (không chạy trên Windows)")
if not bash or not shutil.which("sh"):
    finish("• audit: bỏ qua oracle bash (thiếu bash hoặc sh)")
ver = subprocess.run([bash, "-c", "echo ${BASH_VERSION%%(*}"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                     universal_newlines=True, timeout=30).stdout.strip()
if not ver.split(".")[0].isdigit() or int(ver.split(".")[0]) < 5:
    finish(f"• audit: bỏ qua oracle bash (cần bash 5+, máy có bash {ver or '?'})")
os.makedirs(root)
root = os.path.realpath(root)
if not re.fullmatch(r"[A-Za-z0-9/_.-]+", root):
    finish(f"• audit: bỏ qua oracle bash (đường thư mục tạm có ký tự lạ: {root!r})")
d = root
while True:
    if os.path.exists(os.path.join(d, ".git")):
        finish(f"• audit: bỏ qua oracle bash (thư mục tạm {root} nằm trong repo git {d})")
    if os.path.dirname(d) == d:
        break
    d = os.path.dirname(d)

# Bộ sinh cố định: 1–4 dòng, mỗi dòng 1–3 lệnh nối bằng && ; || |, lệnh cuối là lõi `rm -rf <đích>` hay một thân -c. Cấu
# trúc từng làm phân tích đọc sai: nối dòng, comment có `'` lẻ, heredoc đưa vào shell hay làm dữ liệu, bash -c có biến và lồng
# nhau, cd (thành công, lỗi, builtin, nền), subshell, biến (gán, export, unset), `--`, `..`.
RM = ["rm -rf src", "rm -rf src 'x'", "rm -rf $D", "rm -rf $D/a", "rm -rf ${D}src", "rm -rf -- -x", "rm -rf /tmp/w/x -- -x",
      "rm -rf /tmp/w/x", "rm -rf /tmp/w\\\n  src", "rm -rf ../../src", "cd /tmp/w & rm -rf src"]
CD = ["cd /tmp/w", "cd /tmp/w/s", "cd /tmp/nope", "cd src", "cd ..", "cd -", "cd", "cd /", "builtin cd /", "pushd /tmp/w",
      "popd", "(cd /tmp/w)", "(cd /tmp/w && true)", "( cd / )"]
VAR = ["D=/tmp/w", "D=/tmp/w/", "D=/", "D=", "export D=/tmp/w", "export D=/", "unset D", "echo 'a b'", 'echo "a b"', "true"]
SHC = ["bash -c 'rm -rf $D/a'", "sh -c 'rm -rf $D/a'", "bash -lc 'rm -rf src'", "bash -c 'D=/; rm -rf $D'",
       'bash -c "rm -rf $D/a"', 'bash -c "rm -rf \\$D/a"', "bash -c 'cd /tmp/w && rm -rf src'",
       'sh -c "cd /tmp/w; rm -rf src"', "bash -c 'D=/tmp/w'", "bash -c \"bash -c 'rm -rf \\$D'\"",
       "bash -c \"D=/; bash -c 'rm -rf $D'\"", "bash -c 'cd /tmp/w'", "bash -euo pipefail -c 'D=/; rm -rf $D'",
       "bash -c -- 'rm -rf $D/a'"]
LINE = ["bash <<'EOF'", "bash <<EOF", "sh <<'EOF'", "cat <<'EOF' | bash", "cat <<EOF | sh", "cat <<'EOF'", ": <<'EOF'",
        "bash \\\n<<'EOF'", "EOF", "EOF", "# x \\", "# don't", "echo don't"]
TAIL = ["", "", "", "", " \\", " # don't", " # x \\"]
SEP = [" && ", " && ", "; ", " || ", " | "]
rnd = random.Random(1)
def line():
    if rnd.random() < 0.3:
        return rnd.choice(LINE)
    parts = [rnd.choice(CD + VAR + SHC) for _ in range(rnd.randint(0, 2))] + [rnd.choice(RM + SHC)]
    s = parts[0]
    for p in parts[1:]:
        s += rnd.choice(SEP) + p
    return ("(" + s + ")" if rnd.random() < 0.1 else s) + rnd.choice(TAIL)
fuzz = ["\n".join(line() for _ in range(rnd.randint(1, 4))) for _ in range(3000)]
FORBID = re.compile(r"git|push|reset|clean|remove-item|>", re.IGNORECASE)
cmds = [c for c in dict.fromkeys(fuzz + list(known)) if re.search(r"\brm\b", c) and not FORBID.search(c)]

# Mỗi luồng một chỗ chạy: p là thư mục dự án giả (cwd, có src để `cd src && rm …` chạy thật), tmp thay cho /tmp (mục A
# đọc `/tmp/w`, bash chạy ở <chỗ>/tmp/w), stub ghi mỗi lần gọi ra một file riêng (các khâu của ống chạy song song). Không
# xoá gì, chỉ ghi.
STUB = "#!/bin/sh\nprintf '%s\\0' \"$PWD\" \"$@\" > \"$(dirname \"$0\")/log.$$\"\n"
env = {"PATH": os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if os.path.isabs(p)),
       "HOME": os.path.join(root, "khong-co"), "LC_ALL": "C"}
def setup(k):
    base = os.path.join(root, str(k))
    for sub in ("p/src", "tmp/w/s"):
        os.makedirs(os.path.join(base, sub))
    with open(os.path.join(base, "stub"), "w") as fh:
        fh.write(STUB)
    os.chmod(os.path.join(base, "stub"), 0o755)
    return base
def rm_targets(args):
    """Đích của rm như GNU rm đọc: trước `--` đầu tiên, token mở bằng `-` (trừ `-` trơn) là cờ, ở đâu cũng vậy."""
    end = args.index("--") if "--" in args else len(args)
    return [t for t in args[:end] if t and (t == "-" or not t.startswith("-"))] + [t for t in args[end + 1:] if t]
def run(base, cmd, rec=False):
    """(lỗi, các lần gọi stub [(thư mục, đích)], đích ngoài thư mục tạm) khi bash chạy cmd. rec: chỉ tính đích ngoài thư mục
    tạm của lần gọi có cờ đệ quy."""
    tmpd = os.path.join(base, "tmp")
    text = re.sub(r"(/tmp/)|\brm\b", lambda m: tmpd + "/" if m[1] else os.path.join(base, "stub"), cmd)
    if re.search(r"\brm\b", text.replace(root, "")) or FORBID.search(text.replace(root, "")):
        return "văn bản chạy còn rm hay lệnh bị cấm", [], []
    for f in glob.glob(os.path.join(base, "log.*")):
        os.remove(f)
    p = subprocess.Popen([bash, "-c", text], cwd=os.path.join(base, "p"), env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    err = ""
    try:
        p.communicate(timeout=30)  # đọc tới EOF: chờ cả job nền còn giữ stdout (`a && cd x & rm …`)
    except subprocess.TimeoutExpired:
        err = "quá 30 giây"
    try:
        os.killpg(p.pid, signal.SIGKILL)  # tiến trình nào còn sót trong nhóm không được ghi lẫn sang lệnh sau
    except ProcessLookupError:
        pass
    p.wait()
    p.stdout.close()
    calls, bad = [], []
    for f in sorted(glob.glob(os.path.join(base, "log.*"))):
        with open(f, "rb") as fh:
            pwd, *args = fh.read().decode("utf-8", "backslashreplace").split("\0")[:-1] or [""]
        deep = not rec or any(re.fullmatch(r"-[A-Za-z]*[rR][A-Za-z]*|--recursive", t) for t in args)
        for t in rm_targets(args):
            calls.append((pwd, t))
            r = os.path.normpath(os.path.join(pwd, t))
            if deep and r != tmpd and not r.startswith(tmpd + "/"):
                rel = os.path.relpath(r, os.path.join(base, "p"))
                bad.append(r if rel.startswith("../../..") else "<dự án>/" + rel if rel != "." else "<dự án>")
    return err, calls, bad

W = min(8, 2 * (os.cpu_count() or 1))
bases = [setup(k) for k in range(W)]
# Tự kiểm: stub phải được gọi qua `bash -l`, đích trong dự án là nguy, đích trong /tmp/w là vô hại. Hỏng thì xanh giả.
for cmd, want in (("rm -rf src", ["<dự án>/src"]), ("cd /tmp/w && rm -rf src", []),
                  ("bash -lc 'rm -rf /tmp/w/x src'", ["<dự án>/src"])):
    err, calls, bad = run(bases[0], cmd)
    if err or not calls or bad != want:
        fails.append(f"oracle không dựng đúng: {cmd!r}: lỗi {err or 'không'}, stub ghi {calls}, "
                     f"đích ngoài thư mục tạm {bad} (phải là {want})")
if fails:
    finish("")
# Lưới của lớp "thay biến trong thân <<EOF không nháy" ($grid): assert ở bước trên đòi mục A báo mọi lệnh mà mô hình của
# lưới gọi là nguy, ở đây bash thật kiểm mô hình đó (rm đệ quy ngoài thư mục tạm đúng ở các lệnh ấy) và mục A báo đủ.
spec = importlib.util.spec_from_file_location("heredoc_grid", grid_file)
hg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hg)
grid = hg.heredoc_grid()
with ThreadPoolExecutor(W) as ex:
    res = [r for rs in ex.map(lambda k: [(c,) + run(bases[k], c) for c in cmds[k::W]], range(W)) for r in rs]
    gres = [r for rs in ex.map(lambda k: [(c, d, why) + run(bases[k], c, rec=True) for c, d, why in grid[k::W]],
                                range(W)) for r in rs]
shutil.rmtree(root, ignore_errors=True)
model = [(why, c, bad) for c, d, why, _err, _calls, bad in gres if bool(bad) != d]
if model:
    fails.append(f"lưới thân <<EOF: bash thật khác mô hình của lưới ở {len(model)}/{len(grid)} lệnh (sửa heredoc_grid):\n"
                 + "\n".join(f"  {why}: {c!r}: bash xoá đệ quy {bad or 'không gì'}" for why, c, bad in model[:5]))
gmiss = sorted((len(c), why, c) for c, _d, why, err, _calls, bad in gres
               if not err and bad and "xoá đệ quy" not in a.suspicious_labels(c, a.SUSPICIOUS))
fails += [f"{c!r}: {err}" for c, _d, _why, err, _calls, _bad in gres if err]
if gmiss:
    fails.append(f"lưới thân <<EOF: mục A bỏ sót {len(gmiss)} lệnh mà bash xoá đệ quy ngoài thư mục tạm:\n"
                 + "\n".join(f"  {why}: {c!r}" for _n, why, c in gmiss[:10]))
misses, danger, hit = [], 0, set()
for c, err, _calls, bad in res:
    if err:
        fails.append(f"{c!r}: {err}")
    if not bad:
        continue
    danger += 1
    if a.suspicious_labels(c, a.SUSPICIOUS):
        continue
    if c in known:
        hit.add(c)
    else:
        misses.append((len(c), c, sorted(set(bad))))
if danger < len(cmds) // 4:  # bộ sinh hay stub hỏng thì phép so vô nghĩa
    fails.append(f"chỉ {danger}/{len(cmds)} lệnh xoá đích ngoài thư mục tạm: bộ sinh hay stub hỏng")
if misses:
    fails.append(f"mục A bỏ sót {len(misses)} lệnh mà bash xoá đích ngoài thư mục tạm (ngắn nhất trước):\n"
                 + "\n".join(f"  {c!r}: bash xoá {', '.join(bad)}" for _n, c, bad in sorted(misses)[:10])
                 + "\n  Sửa cách segments()/suspicious_labels đọc cấu trúc đó (thêm một cách đọc rồi lấy hợp, như exact hay "
                 "nối dòng). Không ghi thêm vào KNOWN_MISSES: danh sách chỉ được giảm.")
gone = [c for c in known if c not in hit and not a.suspicious_labels(c, a.SUSPICIOUS)]
for c in gone:  # mục A vẫn không báo, mà bash ở máy này không xoá gì ngoài thư mục tạm (sh khác dash?): chỉ ghi chú
    print(f"• audit: oracle bash: ca trong KNOWN_MISSES không tái hiện trên máy này: {c!r}")
finish("" if fails else f"✔ audit: oracle bash: {len(cmds)} lệnh fuzz chạy bằng bash {ver} thật (rm thay bằng stub), "
       f"{danger} lệnh xoá đích ngoài thư mục tạm, mục A báo cả, trừ {len(hit)} ca trong KNOWN_MISSES "
       f"(chỉ được giảm: {ratchet}); lưới thân <<EOF: {len(grid)} lệnh khớp mô hình, mục A báo đủ "
       f"{sum(1 for g in gres if g[5])} lệnh nguy ({time.monotonic() - t0:.0f} giây)")
PYEOF
fi
# Oracle bash: hai bước trên chỉ so với chính audit (bản trước, nhãn mong đợi) nên không bắt được lỗi mà mọi bản cùng có.
# Phân tích lệnh của mục A từng đọc khác bash thật hơn mười lần (1e9882a và 3 lần vá, 3dab000, 5083855, 52233e5..9734b56,
# reviewer chặn nhiều vòng). Bước này sinh lệnh tất định từ một ngữ pháp CHỈ gồm thứ an toàn, chạy bằng bash thật với rm giả
# (`fakerm` ghi $PWD và đích vào log, không xoá gì; PATH chỉ có bash và cat; env tối giản; stdin /dev/null), rồi đòi mục A
# báo mọi lệnh mà bash thật xoá ngoài thư mục tạm/build.
"$py" -I -B - "$tmp/oracle" <<'PYEOF' || status=1
import importlib.util, os, random, re, shlex, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
for s in (sys.stdout, sys.stderr):
    s.reconfigure(encoding="utf-8")  # -I bỏ qua PYTHONIOENCODING
sbx = sys.argv[1]
# Số lệnh nguy hiểm (bash thật xoá ngoài thư mục tạm/build) mà ngữ pháp dưới sinh ra phải ít nhất bằng ORACLE_FLOOR. Đo
# trên bash 5.2 ở ngữ pháp gốc (trước lô thêm): 2655/4294 lệnh, trong đó 165 lệnh có cd nhiều tham số. bash 5.2 báo lỗi với
# cd nhiều tham số, còn bash 3.2 (/bin/bash của macOS) vào tham số đầu, nên các lệnh đó có thể hết nguy hiểm: sàn là
# 2655 - 165 = 2490, làm tròn xuống. Số so với sàn này đếm cả lô thêm (cả hai: 3615/5677 lệnh), nên bỏ lô thêm vẫn qua sàn.
# ORACLE_FLOOR_EXTRA canh riêng lệnh do chính hàm lst thứ hai sinh (EXTRA, không qua lst_base): đo 586, trong đó 12 có cd
# nhiều tham số và 62 có `|&` (bash 3.2 chưa có: lỗi cú pháp, rm không chạy), sàn là 586 - 12 - 62 = 512, làm tròn xuống.
# Bỏ lô thêm hay bỏ hàm lst thứ hai (lô thêm vẫn có 953 lệnh nguy hiểm, mọi lệnh qua lst_base) thì EXTRA rỗng. CHỈ ĐƯỢC
# NÂNG các sàn. Hạ sàn, bớt N, bỏ cấu trúc hay đổi trọng số làm ít lệnh nguy hiểm đi là bớt test cho dễ: ca bỏ sót thì
# sửa phân tích lệnh trong audit-agent.py.
# Lô var_trap2 (port blissful-dirac 78e474a) đo trên bash 5.2: tổng 4612/7090 lệnh nguy hiểm (364 có cd nhiều tham số hay
# `|&`), nên ORACLE_FLOOR nâng 2400 lên 2600 như 78e474a. ORACLE_FLOOR_TRAP2 canh riêng lệnh do var_trap2 sinh ở mức ngoài
# cùng (TRAP2): đo 505, trong đó 14 có cd nhiều tham số hay `|&`, sàn là 505 - 14 = 491, làm tròn xuống.
ORACLE_FLOOR = 2600
ORACLE_FLOOR_EXTRA = 500
ORACLE_FLOOR_TRAP2 = 450
N = 4500  # khoảng 12 giây trên 4 CPU
# KNOWN_GAPS: lỗ đã biết, có việc riêng, nên ngữ pháp KHÔNG sinh. Bỏ một dòng khỏi đây chỉ khi audit đã sửa lỗ đó, và thêm
# cấu trúc tương ứng vào ngữ pháp cùng lúc.
#   - nháy lẻ cặp không thoát, chuỗi trải nhiều dòng (ngữ pháp chỉ có nháy trọn cặp trên một dòng, `\'` và nháy trong comment)
#   - heredoc không đóng (dòng EOF luôn đứng riêng, không kèm comment)
#   - bash -c; ssh, source, `. /dev/stdin` đọc heredoc
#   - `&#`, `(#` (comment luôn có khoảng trắng trước `#`, không đứng sát `&` hay `(`)
#   - biến môi trường kế thừa (bash chạy với env chỉ có HOME và PATH)
#   - delimiter heredoc không phải `[A-Za-z_]\w*` (`EOF.x`, `EOF-1`), dòng kết thúc CRLF
if os.name == "nt" or not re.fullmatch(r"[A-Za-z0-9_./-]+", sbx):
    print(f"• audit: bỏ qua oracle bash (cần đường tạm POSIX không phải đặt trong nháy, có {sbx!r})")
    sys.exit(0)
spec = importlib.util.spec_from_file_location("audit_oracle", "scripts/audit-agent.py")
au = importlib.util.module_from_spec(spec)
spec.loader.exec_module(au)
t0 = time.time()
# Sandbox nằm dưới thư mục tạm của hệ thống, nên audit coi MỌI đường tuyệt đối trong đó là thư mục tạm. Vì thế đường tuyệt
# đối duy nhất trong ngữ pháp là REAL (thư mục tạm có thật) và GONE (không tồn tại, chỉ làm đích cd: cd lỗi).
REAL, GONE, PROJ, HOME, BIN, LOG = (os.path.join(sbx, n) for n in ("tmpw", "khongco", "proj", "home", "bin", "log"))
for d in (REAL + "/src", REAL + "/dist", HOME, BIN, LOG) + tuple(PROJ + "/" + n for n in ("src", "dist", "node_modules", "build")):
    os.makedirs(d, exist_ok=True)
for tool in ("bash", "cat"):
    os.symlink(shutil.which(tool), os.path.join(BIN, tool))

RM = object()  # chỗ chữ lệnh xoá trong mảnh lệnh: bản audit là `rm`, bản bash là `fakerm`
rnd = random.Random(7)
pick = rnd.choice
CD_T = [REAL] * 6 + [GONE] * 3 + ["dist", "node_modules", "src", "..", "/", "~", "-"]
# Đích có biến sau phần trông lành, và giá trị đưa nó ra ngoài (`x /` tách thành hai đích): audit không thay được biến thì đích
# chữ trông vô hại.
VAR_T = [REAL + "/$D", "node_modules/$D", "dist/$D"]
D_OUT = ["..", "../..", "../proj", '"x /"']
RM_T = ["src"] * 6 + [".", "$D", "$D/src", "-- -x", "dist src", "dist", "node_modules/x", "build", REAL + "/x", "~/x", "../src"] + VAR_T
D_V = [REAL, REAL, "src", "dist", "/", "~"] + D_OUT
COMMENT = ["# a", "# a ; b", "# a && b", "# a | b", "# x &&", "# x |", "# cd " + REAL + " &&", "# cd dist"]
OTHER = ["true"] * 4 + ["false"] * 2 + [":", "echo a", "popd", "wait", "echo a\\|#b", "echo a\\|#b"]
P_HD, P_COMP, P_CD, P_RM, P_OTHER = .15, .25, .35, .3, .25
P_OPC, P_TRC, P_LINEC = .3, .3, .1  # comment sau &&/||/|, cuối dòng, dòng riêng
TOPLEN = [1, 2, 2, 3, 3, 4]
P_TRAP = .5
P_VAR = .3  # trong các bẫy: bẫy biến


def cd():
    r = rnd.random()
    if r < 0.08:
        return "cd"
    if r < 0.14:
        return "cd %s %s" % (pick(CD_T), pick(CD_T))
    w = pick(["cd"] * 6 + ["builtin cd", "pushd"])
    return w + " " + pick([t for t in CD_T if t != "-"] if w == "builtin cd" else CD_T)  # builtin cd - in ra stdout


def simple(assign=True):
    """(mảnh, là phép gán)."""
    r = rnd.random()
    if r < P_CD:
        return [cd()], False
    if r < P_CD + P_RM:
        return [RM, " -rf " + pick(RM_T)], False
    if r < P_CD + P_RM + P_OTHER or not assign:
        return [pick(OTHER)], False
    return [pick(["D=", "export D="]) + pick(D_V)], True


def item(depth, top):
    """(mảnh, loại, có phép gán chạy ở shell này): loại "assign" (phép gán trơn), "heredoc" hay ""."""
    r = rnd.random()
    if top and r < P_HD:
        return heredoc(), "heredoc", False
    if depth < 2 and r < P_HD + P_COMP:
        inner, ga = lst(depth + 1, False)
        k = rnd.randrange(4)
        if k == 0:
            return ["( "] + inner + [" )"], "", False
        if k == 1:
            return ["{ "] + inner + ["; }"], "", ga
        return [pick(["true $( ", "echo $( "])] + inner + [" )"], "", False
    p, a = simple()
    return p, "assign" if a else "", a


def heredoc():
    """Heredoc đưa vào shell, độ sâu 1: thân rỗng hay là một danh sách lệnh của chính ngữ pháp."""
    opener = pick(["bash <<'EOF'", "bash <<EOF", "cat <<'EOF' | bash", "cat <<EOF | bash", "cat <<'EOF' \\\n| bash"])
    r = rnd.random()
    if r < 0.15:
        suffix = [pick([" && ", " || "])] + simple(assign=False)[0]
    elif r < 0.25:
        suffix = ["; "] + simple()[0]
    else:
        suffix = []
    body = [] if rnd.random() < 0.2 else lst(1, False)[0]
    return [opener] + suffix + ["\n"] + body + (["\n"] if body else []) + ["EOF"]


def trap_items(depth, top):
    """Bẫy: nhiễu, một chỗ làm audit tin là thư mục tạm (cd vào REAL/GONE, D=REAL, comment có cd vào REAL), nhiễu, rồi rm
    đích tương đối. Ngẫu nhiên thuần gần như không sinh ra được các cấu trúc từng làm mục A bỏ sót."""
    items = [item(depth, top) for _ in range(rnd.randint(0, 2))]
    t = rnd.random()
    if t < 0.6:
        items.append(([pick(["cd ", "cd ", "pushd ", "builtin cd "]) + pick([REAL, GONE])], "", False))
    elif t < 0.8:
        items.append(([pick(["D=", "export D="]) + REAL], "assign", True))
    else:
        p = simple(assign=False)[0]
        items.append((p + [" # " + pick(["a && ", "", "x; "]) + "cd " + REAL + pick([" &&", "", " |", ";"])], "comment", False))
    if rnd.random() < 0.7:
        items.append(([pick(["true", "false", "echo a\\|#b", "echo a\\|#b"])], "", False) if rnd.random() < 0.6
                     else item(depth, top))
    items.append(([RM, " -rf " + pick(["src", "src", ".", "-- -x", "$D", "$D/src"])], "", False))
    return items


def var_trap(depth, top):
    """Bẫy biến: D gán giá trị đưa đích ra ngoài ở shell này, gán lại trong subshell, trước `&`, trong thân heredoc (không đổi D
    của shell này) hay gán thường, nhiễu, rồi rm đích có $D sau phần trông lành. Cách đọc cũ của audit giữ phép gán lại, cách
    đọc exact bỏ hết biến ở ranh giới shell con: cả hai đều có thể làm đích chữ trông vô hại."""
    items = [item(depth, top) for _ in range(rnd.randint(0, 1))]
    items.append(([pick(["D=", "export D="]) + pick(D_OUT)], "assign", True))
    v = "D=" + pick(D_V)
    k = rnd.randrange(4 if top else 3)  # heredoc chỉ ở mức ngoài cùng, như heredoc()
    if k == 0:
        items.append((["( " + v + " )"], "", False))
    elif k == 1:
        items.append(([v + " & true"], "", False))
    elif k == 2:
        items.append(([v], "assign", True))
    else:
        items.append(([pick(["bash <<'EOF'", "bash <<EOF", "cat <<EOF | bash"]) + "\n" + v + "\nEOF"], "heredoc", False))
    if rnd.random() < 0.5:
        items.append(item(depth, top))
    items.append(([RM, " -rf " + pick(VAR_T)], "", False))
    return items


def lst(depth, top):
    """(mảnh, có phép gán chạy ở shell này)."""
    if rnd.random() < P_TRAP:
        items = var_trap(depth, top) if rnd.random() < P_VAR else trap_items(depth, top)
    else:
        items = [item(depth, top) for _ in range(pick(TOPLEN) if top else rnd.randint(1, 3))]
    out, bg = [], False
    for i, (p, kind, ga) in enumerate(items):
        out += p
        if i == len(items) - 1:
            break
        nga = items[i + 1][2]
        if kind in ("heredoc", "comment"):
            sep = "\n"  # sau EOF hay comment chỉ có xuống dòng
        else:
            sep = pick(["&&", "||", ";", "|", "\n", "&"])
            if (ga and sep == "|") or (nga and sep in ("&&", "||", "|")):
                sep = ";"  # KNOWN_GAPS: gán trong pipeline, gán sau &&/||
        bg = bg or sep == "&"
        if sep == "\n":
            if kind not in ("heredoc", "comment") and rnd.random() < P_TRC:
                out.append(" " + pick(COMMENT))
            out.append("\n")
            if rnd.random() < P_LINEC:
                out.append(pick(COMMENT) + "\n")
        elif sep in ("&&", "||", "|") and rnd.random() < P_OPC:
            out.append(" %s %s\n" % (sep, pick(COMMENT)))
        else:
            out.append(" " + sep + " " if sep != ";" else "; ")
    if bg:
        out.append("\nwait")  # đợi việc chạy nền ghi log xong
    return out, any(ga for _p, _k, ga in items)


def render(p, word):
    return "".join(word if x is RM else x for x in p)


cmds = list(dict.fromkeys(tuple(lst(0, True)[0]) for _ in range(N)))
# Lệnh thêm, Random riêng (lệnh của ngữ pháp trên giữ nguyên): cấu trúc mà KNOWN_GAPS thôi loại khi nhánh tích hợp audit
# merge. `..` viết trong nháy hay sau `\` (đích rm, đích cd, và bẫy: cd vào thư mục tạm rồi rm đích đó); nháy trọn cặp trên
# một dòng, `\'`, nháy trong comment; bẫy gán: D gán trong ống, sau `&&`/`||` hay gán tạm, rồi rm đích có $D.
QDOT = [".'.'/src", '".."/src', ".\\./src", "'..'", ".'.'", '"../src"', ".\\./.\\./x", "'..'/'..'/x"]
RM_T += QDOT
CD_T += [".'.'", '".."', ".\\.", "'../..'"]
COMMENT += ["# don't", "# it's && x", "# a 'b' c", '# say "hi"']
OTHER += ["echo don\\'t", "echo 'a b'", 'echo "a b"']
lst_base, EXTRA = lst, set()


def lst(depth, top):
    r = rnd.random()
    if r < 0.4:
        return lst_base(depth, top)
    items = [item(depth, top) for _ in range(rnd.randint(0, 2))]
    if r < 0.6:
        items.append(([pick(["cd ", "pushd ", "builtin cd "]) + REAL + " &&"], "", False))
        target = pick(QDOT)
    else:
        v = pick(["D=", "export D="]) + pick(D_V)
        k = rnd.randrange(4)
        if k == 0:
            items.append(([v + pick([" | true", " |& true"])], "", False))
        elif k == 1:
            items.append(([pick(["true", "false"]) + pick([" && ", " || "]) + v], "", False))
        elif k == 2:
            items.append(([pick(["true | ", "false || "]) + v], "", False))
        else:
            items.append(([v + " true"], "", False))
        target = pick(["$D", "$D/src", "src"] + VAR_T)
    items.append(([RM, " -rf " + target], "", False))
    out = []
    for i, (p, kind, _ga) in enumerate(items):
        out += p
        if i < len(items) - 1:
            out.append(" " if p[-1].endswith("&&") else "\n" if kind in ("heredoc", "comment") else pick(["; ", "\n", " && "]))
    if depth == 0:
        EXTRA.add(tuple(out))  # lệnh do chính hàm này sinh, không qua lst_base: ORACLE_FLOOR_EXTRA đếm chúng
    return out, False


rnd.seed(1009)
cmds = list(dict.fromkeys(cmds + [tuple(lst(0, True)[0]) for _ in range(1500)]))
# Lô thêm thứ hai, hạt riêng (lệnh của hai lô trên giữ nguyên): ngữ pháp oracle của blissful-dirac 876ad37, 78e474a (WIP
# e69f5dd). Bẫy biến: D gán giá trị đưa đích ra ngoài ở shell này, rồi D được đặt lại ở chỗ có thể không đổi D của shell này:
# đối số của builtin (`true D=…`), gán tạm (`D=… true`), trong ống, sau `&&`/`||`, trong `if`, `while`, thân hàm có gọi hay
# không (`f() {`, `function f {`), `local` trong và ngoài hàm, nhóm `{ }` kể cả trong ống, rồi rm đích có $D sau phần trông
# lành. Các khâu ghép nhau bằng mọi dấu ngắt, trừ phép gán D ra ngoài phải chạy ở shell này (không sát `|`, không sau
# `&&`/`||`), không thì bẫy hết tác dụng. Thân heredoc và lệnh ghép lồng (item) cũng sinh từ đây.
lst_extra = lst


def var_trap2(depth, top):
    items = [item(depth, top) for _ in range(rnd.randint(0, 1))]
    items.append(([pick(["D=", "export D="]) + pick(D_OUT)], "out", False))
    v = "D=" + pick(D_V)
    k = rnd.randrange(13 if top else 12)  # heredoc chỉ ở mức ngoài cùng, như heredoc()
    if k == 0:
        p = ["( " + v + " )"]
    elif k == 1:
        p = [v + " & true"]
    elif k == 2:
        p = [v]
    elif k == 3:
        p = [pick(["true ", ": "]) + v]
    elif k == 4:
        p = [v + " true"]
    elif k == 5:
        p = [pick([v + " | true", "true | " + v])]
    elif k == 6:
        p = [pick(["true", "false"]) + pick([" && ", " || "]) + v]
    elif k == 7:
        p = ["if " + pick(["true", "false"]) + "; then " + v + "; fi"]
    elif k == 8:
        p = [pick(["f() { ", "function f { "]) + v + "; }" + pick(["", "; f"])]
    elif k == 9:
        p = [pick(["{ " + v + "; }", "{ " + v + "; } | true", "true | { " + v + "; }"])]
    elif k == 10:
        p = [pick(["while false", "until true"]) + "; do " + v + "; done"]
    elif k == 11:
        p = [pick(["local " + v, "f() { local " + v + "; }; f"])]
    else:
        p = [pick(["bash <<'EOF'", "bash <<EOF", "cat <<EOF | bash", "cat <<'EOF' | bash"]) + "\n" + v + "\nEOF"]
    items.append((p, "heredoc" if k == 12 else "", False))
    if rnd.random() < 0.5:
        items.append(item(depth, top))
    items.append(([RM, " -rf " + pick(VAR_T)], "", False))
    out, bg = [], False
    for i, (p, kind, _ga) in enumerate(items):
        out += p
        if i == len(items) - 1:
            break
        if kind in ("heredoc", "comment"):
            sep = "\n"
        else:
            sep = pick(["&&", "||", ";", "|", "\n", "&"])
            if (kind == "out" and sep == "|") or (items[i + 1][1] == "out" and sep in ("&&", "||", "|")):
                sep = ";"  # bẫy biến hết tác dụng khi phép gán D ra ngoài không chạy ở shell này
        bg = bg or sep == "&"
        if sep == "\n":
            if kind not in ("heredoc", "comment") and rnd.random() < P_TRC:
                out.append(" " + pick(COMMENT))
            out.append("\n")
        elif sep in ("&&", "||", "|") and rnd.random() < P_OPC:
            out.append(" %s %s\n" % (sep, pick(COMMENT)))
        else:
            out.append(" " + sep + " " if sep != ";" else "; ")
    if bg:
        out.append("\nwait")
    return out


def lst(depth, top):
    if rnd.random() < 0.5:
        return lst_extra(depth, top)
    out = var_trap2(depth, top)
    if depth == 0:
        TRAP2.add(tuple(out))
    return out, False


TRAP2 = set()
rnd.seed(2600)
cmds = list(dict.fromkeys(cmds + [tuple(lst(0, True)[0]) for _ in range(1500)]))
# Builtin in ra stdout ở vế trái một pipe bị SIGPIPE tuỳ lúc (kết quả không tất định): bọc chúng cho im, giữ mã thoát.
# `wait` không đối số trong $( ) của bash 5.3 (Ubuntu 26.04, runner CI) lặp mãi với việc nền mà shell cha chưa thu, in
# "pid N is not a child of this shell" mỗi vòng: `true & x=$( wait )` treo, còn bash 5.2 trả về ngay. Bọc thành wait từng
# pid của `jobs -p` (pid không phải con thì builtin trả về ngay) và trả 0 như wait không đối số.
PRELUDE = r"""fakerm() {
  local a e=
  printf 'C\t%s\n' "$PWD" >> LOG
  for a in "$@"; do
    if [ -z "$e" ]; then
      if [ "$a" = -- ]; then e=1; continue; fi
      case $a in -?*) continue;; esac
    fi
    printf 'T\t%s\t%s\n' "$PWD" "$a" >> LOG
  done
}
cd() { builtin cd "$@" >/dev/null; }
pushd() { builtin pushd "$@" >/dev/null; }
popd() { builtin popd "$@" >/dev/null; }
echo() { builtin echo "$@" >/dev/null; }
wait() {
  if [ $# -eq 0 ]; then
    set -- $(jobs -p)
    [ $# -eq 0 ] || builtin wait "$@" 2>/dev/null
    return 0
  fi
  builtin wait "$@"
}
export -f fakerm cd pushd popd echo wait
"""


def run(i):
    log = os.path.join(LOG, "%d.log" % i)
    open(log, "w").close()
    script = os.path.join(LOG, "%d.sh" % i)
    with open(script, "w") as f:
        f.write(PRELUDE.replace("LOG", shlex.quote(log)) + render(cmds[i], "fakerm") + "\n")
    try:
        r = subprocess.run([os.path.join(BIN, "bash"), script], cwd=PROJ, env={"HOME": HOME, "PATH": BIN},
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
        err, to = r.stderr.decode("utf-8", "replace"), False
    except subprocess.TimeoutExpired:
        err, to = "", True
    with open(log) as f:
        calls = [ln.rstrip("\n").split("\t")[1:] for ln in f if ln.startswith("T\t")]
    return calls, err, to


with ThreadPoolExecutor(max_workers=(os.cpu_count() or 2) * 2) as ex:
    results = list(ex.map(run, range(len(cmds))))
rreal, rsbx = os.path.realpath(REAL), os.path.realpath(sbx)


def inside(p, d):
    return p == d or p.startswith(d + os.sep)


def dangerous(pwd, t):
    """Nguy hiểm trừ khi đích thật nằm trong REAL hay có thành phần dist/node_modules/build sau sandbox (audit coi tên đó
    vô hại ở mọi chỗ: đó là luật của audit, không phải lỗi đọc lệnh). Dự án giả, src, HOME, cha dự án, /, /src: nguy hiểm."""
    p = os.path.realpath(os.path.join(pwd, t))
    if inside(p, rreal):
        return False
    parts = os.path.relpath(p, rsbx) if inside(p, rsbx) else p
    return not set(parts.split(os.sep)) & {"dist", "node_modules", "build"}


danger, miss, timeouts = 0, [], []
danger_extra = danger_trap2 = 0
for i, (calls, err, to) in enumerate(results):
    c = render(cmds[i], "rm")
    if to:
        timeouts.append(c)
    bad = [(pwd, t) for pwd, t in calls if dangerous(pwd, t)]
    if not bad:
        continue
    danger += 1
    danger_extra += cmds[i] in EXTRA
    danger_trap2 += cmds[i] in TRAP2
    if "xoá đệ quy" not in au.suspicious_labels(c, au.SUSPICIOUS, "Bash"):
        miss.append((len(c), c, bad, err))
el = time.time() - t0
fail = False
short = lambda s: s.replace(sbx, "$SBX")
for c in timeouts[:5]:
    print(f"✘ audit: oracle bash: lệnh chạy quá 10 giây (log có thể thiếu): {short(c)!r}", file=sys.stderr)
    fail = True
if miss:
    fail = True
    print(f"✘ audit: mục A bỏ sót {len(miss)}/{danger} lệnh mà bash thật xoá ngoài thư mục tạm/build ($SBX={sbx}, cwd "
          "$SBX/proj, $SBX/tmpw là thư mục tạm có thật), ngắn nhất trước:", file=sys.stderr)
    for _n, c, bad, err in sorted(miss)[:None if os.environ.get("AUDIT_LOST_ALL") else 10]:
        print(f"  {short(c)!r}", file=sys.stderr)
        for pwd, t in bad[:3]:
            print(f"    bash: PWD={short(pwd)} đích={short(t)}", file=sys.stderr)
        if err.strip():
            print("    stderr: " + short(err.strip())[:300].replace("\n", "\n            "), file=sys.stderr)
    print("  Sửa phân tích lệnh trong audit-agent.py (segments, benign_delete) cho tới khi mục A báo các lệnh này, và thêm "
          "ca ngắn nhất vào fixture. Đừng bỏ cấu trúc khỏi ngữ pháp, trừ khi đó là lỗ có việc riêng: khi đó ghi vào "
          "KNOWN_GAPS. AUDIT_LOST_ALL=1 in đủ.", file=sys.stderr)
if danger < ORACLE_FLOOR:
    fail = True
    print(f"✘ audit: oracle bash chỉ sinh {danger} lệnh nguy hiểm, dưới sàn ORACLE_FLOOR={ORACLE_FLOOR}. Ngữ pháp vừa bị "
          "thu nhỏ hay bash chạy khác đi. Thêm cấu trúc vào ngữ pháp (hay trả lại cấu trúc đã bỏ) cho đủ sàn; đừng hạ sàn.",
          file=sys.stderr)
if danger_extra < ORACLE_FLOOR_EXTRA:
    fail = True
    print(f"✘ audit: lệnh thêm của oracle bash (hàm lst thứ hai) chỉ có {danger_extra} lệnh nguy hiểm, dưới sàn "
          f"ORACLE_FLOOR_EXTRA={ORACLE_FLOOR_EXTRA}. Lô thêm hay hàm lst thứ hai vừa bị bỏ, thu nhỏ, hay bash chạy khác đi. "
          "Trả lại cấu trúc đã bỏ cho đủ sàn; đừng hạ sàn.", file=sys.stderr)
if danger_trap2 < ORACLE_FLOOR_TRAP2:
    fail = True
    print(f"✘ audit: bẫy biến của lô thêm thứ hai (var_trap2) chỉ có {danger_trap2} lệnh nguy hiểm, dưới sàn "
          f"ORACLE_FLOOR_TRAP2={ORACLE_FLOOR_TRAP2}. Lô hay hàm var_trap2 vừa bị bỏ, thu nhỏ, hay bash chạy khác đi. "
          "Trả lại cấu trúc đã bỏ cho đủ sàn; đừng hạ sàn.", file=sys.stderr)
if fail:
    sys.exit(1)
print(f"✔ audit: oracle bash: mục A báo đủ {danger} lệnh mà bash thật xoá ngoài thư mục tạm/build ({len(cmds)} lệnh sinh, "
      f"sàn {ORACLE_FLOOR}; {danger_extra} từ hàm lst thứ hai, sàn {ORACLE_FLOOR_EXTRA}; {danger_trap2} từ var_trap2, sàn "
      f"{ORACLE_FLOOR_TRAP2}; {el:.1f}s)")
PYEOF
rm -rf "$tmp/oracle"

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
