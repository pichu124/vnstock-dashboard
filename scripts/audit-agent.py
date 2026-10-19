#!/usr/bin/env python3
"""Dò sự cố của đội agent từ file phiên của Claude Code (~/.claude/projects/<dự án>/**/*.jsonl).

Chỉ đọc. Lập báo cáo markdown (hoặc JSON) gồm:
  A. lệnh nghi nguy hiểm đã CHẠY mà guard hiện tại không hỏi (ứng viên guard bỏ sót)
  B. hồi quy: trước đây guard hỏi, guard hiện tại lại cho qua
  C. guard hỏi và người duyệt (ứng viên hỏi thừa), D. guard hỏi và người từ chối (guard làm đúng)
  E. Stop gate: số lần chặn, nhả sau N lần, thời gian chạy
  F. lỗi hook của kit
  G. người từ chối mà guard không hỏi, H. lệnh đã chạy lúc guard không hỏi mà bản hiện tại hỏi
     (guard chưa nạp, workspace chưa trust, matcher thiếu tool, hoặc bản cũ)
  I. lần bạn phải sửa agent (ngắt, từ chối kèm lời, câu sửa): ứng viên cho /correct
  J. chỉ số theo tuần × dự án: lượt hỏi, lần sửa, Stop gate chặn, kết luận của verifier và reviewer
Thường gọi qua scripts/audit-agent.sh (để có bash chạy lại guard). Cần Python 3.8+, chỉ thư viện chuẩn.
Mặc định soát dự án ở thư mục hiện tại; --all soát mọi dự án trên máy (khi kit cài dạng plugin).
"""
import argparse
import collections
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SHELL_TOOLS = ("Bash", "PowerShell")
# Guard của chính bộ kit chứa script này: dùng cho dự án không có bản guard riêng (kit cài dạng plugin).
KIT_GUARD = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard-irreversible.sh"
REJECT_PREFIX = "The user doesn't want to proceed"
REJECT_SAID = "the user said:"  # từ chối kèm lời: phần sau là lời bạn gõ
INTERRUPT_PREFIX = "[Request interrupted by user"  # có biến thể "... for tool use]"
COMMAND_TAG = re.compile(r"<command-(message|name)>")  # slash command: chữ dò lấy từ <command-args>
# Ngữ cảnh máy chèn TRƯỚC lời bạn trong cùng tin (file đang mở trong IDE, system-reminder): bỏ đi, giữ phần sau.
CONTEXT_PREFIX = re.compile(r"^(?:\s*<(ide_[\w-]+|system-reminder)>.*?</\1>)*\s*", re.DOTALL)
# Tin mở bằng các thẻ này là máy ghi (lệnh ! và output, lệnh /local, báo task xong); mở bằng < khác là bạn dán vào.
MACHINE_TAGS = ("<local-command-", "<bash-input>", "<bash-stdout>", "<bash-stderr>", "<task-notification>")
# Báo cáo cuối của subagent (2.1.300+) đi qua tool này chứ không qua block text: dòng KẾT LUẬN nằm trong input.
HANDBACK_TOOL = "SubagentHandback"
VERDICT_RE = re.compile(r"KẾT LUẬN:\W*(PASS|FAIL|INCONCLUSIVE|KHÔNG CHẶN|CHẶN)\b")
# Câu bạn gõ để sửa agent (mục I). Dò bằng từ khoá nên có thể khớp thừa; đừng thêm cụm hay gặp trong câu hỏi
# thường ("đúng không", "lỗi sai chính tả"). Chữ được chuẩn hoá NFC và gộp khoảng trắng trước khi so.
CORRECTION_RE = re.compile(
    r"\b(sai rồi|bị sai|làm sai|vẫn sai|vẫn lỗi|vẫn còn lỗi|vẫn bị|lại lỗi|lại sai|chưa đúng|không đúng"
    r"|không phải thế|không phải vậy|nhầm rồi|bạn nhầm|bạn quên|đã bảo rồi|đã bảo là|tôi bảo rồi|nói rồi mà"
    # không có "tôi đã bảo" (bảo vệ, bảo mật) hay "vẫn chưa được/chạy" (hỏi trạng thái: "vẫn chưa được merge à?")
    r"|lần thứ hai|vẫn không được|vẫn ko được|vẫn không chạy"
    r"|ko đúng|k đúng|ko phải thế|ko phải vậy"  # gõ tắt "ko"
    r"|sai roi|van loi|van sai|khong dung|chua dung|nham roi"  # gõ không dấu
    r"|wrong|incorrect|not what i|still (broken|failing|wrong)|you forgot|i told you)\b",
    re.IGNORECASE)
FIX_KINDS = ("interrupt", "reject_note", "correction")

# Danh sách nghi ngờ RỘNG hơn guard: ý kiến thứ hai để tìm chỗ guard bỏ sót. Khớp thừa chỉ thêm
# một dòng vào báo cáo. Thêm mẫu riêng của dự án trong .claude/audit-watch.txt (regex<TAB>nhãn).
SUSPICIOUS = [
    (r"\bpush\b.*(\s--force\b|\s-f\b|\s--delete\b|\s--mirror\b|\s-d\b|\s\+\S|\s:\S)", "force-push / xoá nhánh remote"),
    (r"\bpush\b.*\b(main|master|trunk|production|release)\b", "push lên nhánh chính"),
    (r"\breset\b.*--hard", "git reset --hard"),
    (r"\bclean\b.*(\s-\w*f|\s--force\b)", "git clean -f"),
    (r"\bcheckout\b\s+(--\s+)?\.(\s|$)|\bcheckout\b.*\s--\s", "git checkout -- (bỏ thay đổi)"),
    (r"\brestore\b(?=.*--worktree|(?!.*--staged))", "git restore (bỏ thay đổi)"),
    (r"\bcheckout\b.*\s(-f|--force)\b", "git checkout -f (bỏ thay đổi)"),
    (r"\bstash\s+(drop|clear)\b", "git stash drop/clear"),
    # -D phân biệt hoa thường (mẫu so không phân biệt): -d chỉ xoá nhánh đã gộp, git tự từ chối nhánh chưa gộp.
    (r"\bbranch\b.*(\s(?-i:-D)\b|\s--delete\s+--force\b|\s-d\s+(-f|--force)\b)", "xoá nhánh local (-D)"),
    (r"\b(rm|remove-item|ri|del|erase|rd|rmdir)\b.*(\s-\w*r\w*\b|\s-recurse\b|\s--recursive\b|\s/s\b)", "xoá đệ quy"),
    (r"\b(drop\s+(table|database|schema)|truncate\s+table|dropdb)\b", "xoá dữ liệu SQL"),
    (r"\b(migrate\s+reset|db:(drop|reset))\b", "reset database"),
    (r"\b(npm|pnpm|yarn|bun|cargo)\b.*\bpublish\b|\btwine\s+upload\b|\bdocker\b.*\bpush\b", "publish / đẩy artifact"),
    (r"\b(terraform|kubectl|helm)\b.*\b(apply|destroy|delete|upgrade|install|uninstall|rollback|scale|drain)\b", "thay đổi hạ tầng"),
    (r"\bdeploy\b|--prod\b", "deploy"),
    (r"\bgh\b.*\b(pr\s+merge|release\s+create|repo\s+delete)\b", "merge PR / release / xoá repo"),
    (r"\bgit\b.*\bfilter-(branch|repo)\b", "viết lại lịch sử git"),
]


def project_key(path):
    """Tên thư mục trong ~/.claude/projects: mọi ký tự không phải chữ/số thành '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def load_watch(root):
    pats = []
    f = root / ".claude" / "audit-watch.txt"
    if f.is_file():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                rx, _, label = line.partition("\t")
                try:
                    re.compile(rx)
                    pats.append((rx.strip(), label.strip() or "mẫu riêng của dự án"))
                except re.error as exc:
                    print(f"⚠ bỏ qua mẫu hỏng trong {f}: {rx!r} ({exc})", file=sys.stderr)
    return pats


HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1([^\n]*)\n(.*?)(\n[ \t]*\2[ \t]*(\n|$)|\Z)", re.DOTALL)
PIPE_SHELL = re.compile(r"^\s*\|\s*(bash|sh|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b", re.IGNORECASE)
SHELL_WORD = re.compile(r"\b(bash|sh|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b[^\n|;&]*$", re.IGNORECASE)
SPLIT = re.compile(r"\n|;|&&|\|\||\|")
SHELL_C = re.compile(r"\b(bash|sh|zsh|dash|pwsh|powershell)(\.exe)?\s+(-\w+\s+)*-c(ommand)?\s|\bcmd(\.exe)?\s+(/\w\s+)*/[ck]\s|\beval\s"
                     r"|\|\s*(bash|sh|zsh|dash|pwsh|powershell)(\.exe)?\b",
                     re.IGNORECASE)
QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
QUOTED_PS = re.compile(r"\"[^\"]*\"|'[^']*'")  # PowerShell không escape bằng \ ("C:\x\" là một chuỗi trọn)
ASSIGN = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)")
CD = re.compile(r"^(cd|pushd|set-location|sl|push-location)\s+(.+)$", re.IGNORECASE)
TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")
# Xoá đệ quy chỉ được coi là vô hại khi MỌI đích nằm trong thư mục tạm/build (khớp trọn tên một thành phần)
# hoặc trong worktree tạm của subagent (AGENT_WORKTREE).
BENIGN_NAMES = {"tmp", "temp", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
                ".ruff_cache", ".cache", "coverage", ".coverage", "htmlcov", ".venv", "venv", ".tox", ".next",
                ".turbo", ".parcel-cache", "scratchpad"}
CMD_FLAG = re.compile(r"^/[a-z]$", re.IGNORECASE)
# Subagent dọn worktree tạm của chính nó. Vô hại chỉ khi đích ghi TRỌN là .claude/worktrees/agent-<hex>[/...] (chỉ chữ,
# số, _./\:~-: không biến, glob, brace, dấu phẩy, khoảng trắng), hay cả đoạn lệnh chỉ xoá nhánh worktree-agent-<hex>.
# Sau agent-<hex> chỉ nhận `/`: với bash `\` là ký tự thoát, `agent-abc\` nối đích với dòng kế (hay `; x`, `| x`) và
# `agent-abc\-old` là thư mục khác nằm cạnh. Đường Windows có `\` sau agent-<hex> vì thế bị báo thừa.
# Không dùng thư mục suy theo cd: shell có quá nhiều đường thoát (subshell, bash -c, eval, `&`...).
AGENT_WORKTREE = re.compile(r"^(?:[A-Za-z]:)?[A-Za-z0-9_./\\:~-]*?[\\/]?\.claude[\\/]worktrees[\\/]agent-[0-9a-f]+"
                            r"((?:/[A-Za-z0-9_.-]+)*)/?$")
PS_NAMED = re.compile(r"^-[\w-]+:")  # -Path:C:\x của PowerShell: đích nằm trong một token trông như cờ
AGENT_BRANCH_DELETE = re.compile(r"^git\s+branch\s+(?:-D|--delete\s+--force|-d\s+(?:-f|--force)|-f\s+-d)"
                                 r"(?:\s+worktree-agent-[0-9a-f]+)+$")
TAIL_REDIRECT = re.compile(r"(?:\s+[\d&]?>>?\s*(?:&\d|/dev/null))+$")  # 2>&1, >/dev/null... ở cuối đoạn lệnh


def expand(text, env):
    for name, val in env.items():
        text = re.sub(r"\$\{?" + name + r"\b\}?", lambda _m, v=val: v, text)
    return text


def keep_shell_heredocs(cmd):
    """Thân heredoc là dữ liệu, trừ khi nó được đưa vào một shell (bash <<'X' ... X): khi đó là lệnh."""
    def sub(m):
        line_start = m.string.rfind("\n", 0, m.start()) + 1
        rest = m.group(3)  # phần còn lại của dòng mở heredoc vẫn là lệnh: `; git ...`, `| bash`
        fed = SHELL_WORD.search(m.string[line_start:m.start()]) or PIPE_SHELL.match(rest)
        return rest + "\n" + (m.group(4) + "\n" if fed else "")
    return HEREDOC.sub(sub, cmd)


def segments(cmd, tool="Bash", join=True):
    """Các lệnh đơn trong một lệnh shell, dạng (để so mẫu, đầy đủ, thư mục cd gần nhất, có `$` trước khi thay biến).

    Bản để so mẫu thay chuỗi trong nháy bằng "" (trừ bash -c '...', cmd /c "...", eval), bản đầy đủ
    giữ nguyên để biết đích thật. Biến gán trong lệnh (S=/tmp/x; rm -rf $S) được thay theo thứ tự.
    join=False: không nối dòng tại `\\` + xuống dòng, tách như cũ.
    """
    body = keep_shell_heredocs(cmd)
    if join and tool != "PowerShell":  # nối dòng như bash trước khi tách: bỏ `\` + xuống dòng, trừ khi `\` đó bị thoát (`\\`)
        body = re.sub(r"(?<!\\)((?:\\\\)*)\\\n", r"\1", body)
    store = []

    def keep(m):
        store.append(m.group(0))
        return "\0%d\0" % (len(store) - 1)

    shell_c = bool(SHELL_C.search(body))
    quoted = QUOTED_PS if tool == "PowerShell" else QUOTED
    marked = body if shell_c else quoted.sub(keep, body)
    out, ctx, env = [], "", {}
    for seg in SPLIT.split(marked):
        seg = seg.strip()
        if not seg:
            continue
        raw = re.sub(r"\0(\d+)\0", lambda m: store[int(m.group(1))], seg)
        full = expand(raw, env)
        plain = expand(re.sub(r"\0\d+\0", '""', seg), env)
        if shell_c:
            plain = re.sub(r"[\"']", " ", plain)
        for name, val in ASSIGN.findall(full):
            env[name] = val.strip("\"'")
        head = full.lstrip("({ ")
        m = CD.match(head)
        if m and m.group(2).strip().strip("\"'") not in ("-", ""):
            target = m.group(2).strip().strip("\"'")
            ctx = target if is_absolute(target) else (ctx + "/" + target)
        elif full[:1] in "({" or re.match(r"^(cd|popd|pop-location|pushd|set-location|sl)\s*(-\s*)?$", head, re.IGNORECASE):
            ctx = ""  # cd không tham số, cd -, popd, subshell: không còn biết thư mục
        out.append((plain, full, ctx, "$" in raw))
    return out


def is_absolute(p):
    return bool(re.match(r"^([/\\~]|[A-Za-z]:|\$home\b|\$env:|%)", p, re.IGNORECASE))


def under_temp(p):
    low = p.replace("\\", "/").lower()
    temps = ["/tmp/", "/var/tmp/", "%temp%", "%tmp%", "$env:temp", "$env:tmp", "/appdata/local/temp/"]
    for v in ("TMPDIR", "TEMP", "TMP"):
        if os.environ.get(v):
            temps.append(os.environ[v].replace("\\", "/").lower().rstrip("/") + "/")
    return any(t in low + "/" for t in temps)


def benign_path(p):
    parts = [x.lower() for x in re.split(r"[\\/]+", p) if x]
    return under_temp(p) or any(x in BENIGN_NAMES for x in parts)


def agent_worktree(p):
    """p là đường ghi trọn trong worktree tạm của subagent, sau agent-<hex> không có thành phần `.`
    (`..` ở đâu cũng bị benign_delete chặn trước)."""
    m = AGENT_WORKTREE.search(p)
    return bool(m) and "." not in re.split(r"[\\/]", m.group(1))


def benign_delete(full, ctx, worktree=True):
    """worktree=False: không nhận đích trong worktree agent (đích thật có thể khác đích ghi)."""
    toks = [t.strip("\"'") for t in TOKEN.findall(full)]
    if any(re.split(r"[\\/]", t)[-1].lower() == "xargs" for t in toks):
        return False  # đích đọc từ stdin: không biết
    while toks and toks[0].lower() in ("sudo", "doas", "wsl", "command", "builtin"):
        toks = toks[1:]
    cmd_style = bool(toks) and toks[0].lower() in ("rd", "del", "erase", "rmdir")  # /s /q là cờ của cmd
    args = toks[1:]
    if not [t for t in args if t and not t.startswith("-") and not (cmd_style and CMD_FLAG.match(t))]:
        return False  # như trước: ngoài cờ không thấy đích nào thì không biết lệnh xoá gì
    end = args.index("--") if "--" in args else len(args)  # sau `--` đầu tiên mọi token là đích, kể cả token mở bằng `-`
    targets = [t for t in args[:end] if t and not t.startswith("-") and not (cmd_style and CMD_FLAG.match(t))]
    targets += [t for t in args[end + 1:] if t]
    worktree = worktree and not any(PS_NAMED.match(t) for t in toks)
    for t in targets:
        if ".." in re.split(r"[\\/]+", t):
            return False
        if benign_path(t) or (worktree and agent_worktree(t)):
            continue
        rel = not is_absolute(t)
        if rel and ctx and benign_path(ctx):
            continue
        return False
    return True


def suspicious_labels(cmd, patterns, tool="Bash"):
    labels = []
    ifs = bool(re.search(r"\bIFS\b", cmd))  # IFS khác: giá trị của biến bị tách thành đích khác
    # Đọc `\` cuối dòng theo cả hai cách như guard (hỏi thừa chứ không bỏ sót): nối dòng có thể dán dòng sau vào cd hay
    # thân heredoc làm lệnh xoá trông vô hại, nên chỉ được thêm nghi ngờ. Luôn xét cả hai: `\` cuối heredoc chưa đóng cũng bị nối.
    segs = segments(cmd, tool) if tool == "PowerShell" else segments(cmd, tool, join=False) + segments(cmd, tool)
    for plain, full, ctx, subst in segs:
        for rx, label in patterns:
            if label in labels or not re.search(rx, plain, re.IGNORECASE):
                continue
            # Đích worktree có được nhờ thay biến thì không tin: gán tạm `D=x lệnh` không đổi biến của shell mà ASSIGN vẫn ghi.
            if label == "xoá đệ quy" and benign_delete(full, ctx, worktree=not (subst or ifs)):
                continue
            if label == "xoá nhánh local (-D)" and AGENT_BRANCH_DELETE.search(TAIL_REDIRECT.sub("", full)):
                continue
            labels.append(label)
    return labels


def texts_of(content):
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, list):
        for x in content:
            if isinstance(x, dict):
                if x.get("type") == "text":
                    out.append(x.get("text") or "")
                elif x.get("type") == "tool_result":
                    out += texts_of(x.get("content"))
            elif isinstance(x, str):
                out.append(x)
    return out


def user_rejected(e, c):
    """tool_result c (trong dòng e) là lần bạn bấm No ở hộp xin phép, có hay không kèm lời."""
    return e.get("toolUseResult") == "User rejected tool use" or bool(
        c.get("is_error") and " ".join(texts_of(c.get("content"))).strip().startswith(REJECT_PREFIX))


class Session:
    def __init__(self):
        self.calls = {}        # tool_use_id -> dict
        self.guard = {}        # tool_use_id -> {"asked": bool, "reason": str}
        self.hook_errors = {}  # khoá dòng -> dict
        self.stop_runs = {}    # khoá dòng -> ms
        self.stop_blocks = {}  # (khoá dòng, thứ tự trong dòng) -> "1/3"
        self.stop_releases = set()  # khoá dòng
        self.bad_lines = 0
        self.old_entries = set()  # khoá dòng
        self.events = {}       # mục I, J: khoá khử trùng -> dict {kind, ts, cwd, file, ...}
        self.file_state = {}   # trong file đang đọc: agent đã trả lời chưa, tool gọi gần nhất, kết luận gần nhất, dòng đang xét
        #                        và có lần từ chối lệnh shell nào chưa được agent trả lời hay bạn gõ lượt mới không (after_reject)


def agent_type(path):
    meta = path.with_name(path.name[: -len(".jsonl")] + ".meta.json")
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("agentType") or "subagent"
    except (OSError, ValueError):
        return "subagent" if path.parent.name == "subagents" else "phiên chính"


def ts_of(e):
    t = e.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def norm_path(p):
    p = str(p).replace("\\", "/").rstrip("/").lower()
    m = re.match(r"^/([a-z])(/|$)", p)
    return f"{m.group(1)}:{p[2:]}" if m else p


def parse(path, s, cutoff, only_under=None):
    """only_under: chỉ nhận lệnh có cwd nằm trong thư mục này (file của thư mục phiên khác, cùng tiền tố)."""
    who = agent_type(path)
    s.file_state = {"assistant": False, "doing": "", "tools": {}, "verdict": None, "after_reject": False}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
                if isinstance(e, dict):
                    parse_entry(e, s, path, who, cutoff, only_under)
            except (ValueError, AttributeError, TypeError, KeyError):
                s.bad_lines += 1  # JSON hỏng hoặc sai hình dạng: đếm, không làm hỏng cả lượt
    v = s.file_state["verdict"]
    role = who[len("agent-team:"):] if who.startswith("agent-team:") else who
    if v and role in ("verifier", "reviewer") and in_scope(v["entry"].get("cwd"), only_under):
        add_event(s, v["entry"], path, "verdict", agent=role, verdict=v["verdict"])


def in_scope(cwd, only_under):
    return only_under is None or (norm_path(cwd or "") + "/").startswith(only_under + "/")


def add_event(s, e, path, kind, **extra):
    if ts_of(e) is None:
        return  # không có giờ thì không xếp được vào tuần nào
    st = s.file_state
    if st.get("entry") is not e:
        st["entry"], st["emitted"] = e, collections.Counter()
    n = st["emitted"][kind]  # thứ tự trong dòng: một stop_hook_summary có thể có nhiều lần chặn
    st["emitted"][kind] += 1
    ev = dict(kind=kind, ts=e["timestamp"], cwd=e.get("cwd") or "", file=str(path), **extra)
    key = (e["uuid"], kind, n) if e.get("uuid") else (kind, ev["ts"], ev["cwd"], tuple(sorted(extra.items())), n)
    # Một dòng phiên có thể nằm ở nhiều file (bản chép khi worker khởi động lại hay resume, có khi ghi cwd mới):
    # đếm một lần. Bản đọc sau ghi đè, như s.calls ở mục A–H, để cả báo cáo quy dòng đó về cùng một cwd.
    s.events[key] = ev


def clip(text, n=200):
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def tool_summary(c, wire):
    """Tool và lệnh hoặc file nó đụng tới, để biết agent đang làm gì lúc bị ngắt hay từ chối."""
    inp = wire.get(c.get("id")) or c.get("input") or {}
    name = c.get("name") or "?"
    if isinstance(inp, dict) and isinstance(inp.get("command"), str):
        return f"{name}: {short(inp['command'], 100)}"
    if isinstance(inp, dict) and isinstance(inp.get("file_path"), str):
        return f"{name}: {inp['file_path']}"
    return name


def track_assistant(e, msg, s, fresh):
    st = s.file_state
    st["assistant"] = True
    st["after_reject"] = False
    wire = e.get("wireToolInputs") if isinstance(e.get("wireToolInputs"), dict) else {}
    content = msg.get("content")
    for c in content if isinstance(content, list) else []:
        if not isinstance(c, dict):
            continue
        text = c.get("text") if c.get("type") == "text" else None
        if c.get("type") == "tool_use":
            st["doing"] = st["tools"][c.get("id")] = tool_summary(c, wire)
            if c.get("name") == HANDBACK_TOOL and isinstance(c.get("input"), dict):
                text = c["input"].get("message")
        found = VERDICT_RE.findall(unicodedata.normalize("NFC", text)) if fresh and isinstance(text, str) else []
        if found:
            st["verdict"] = {"verdict": found[-1], "entry": {"timestamp": e.get("timestamp"), "cwd": e.get("cwd"), "uuid": e.get("uuid")}}


def human_text(e, content):
    """Chữ của một tin bạn gõ, đã bỏ ngữ cảnh máy chèn ở đầu từng block; None nếu cả tin do máy chèn (isMeta, tóm tắt compact, ...)."""
    if e.get("isMeta") or e.get("isCompactSummary") or e.get("isVisibleInTranscriptOnly"):
        return None
    origin = e.get("origin")  # bản cũ (Windows 2.1.296) không có origin: vẫn là tin người
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return None
    if isinstance(content, str):
        return CONTEXT_PREFIX.sub("", content, count=1)
    if isinstance(content, list):
        parts = (CONTEXT_PREFIX.sub("", c["text"], count=1) for c in content
                 if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
        return "\n".join(p for p in parts if p)
    return None


def track_user(e, msg, s, path, who, only_under):
    if not in_scope(e.get("cwd"), only_under):
        return
    st = s.file_state
    content = msg.get("content")
    if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
        for c in content:
            # Chỉ lệnh shell (s.calls): lần từ chối đó đã có ở D/G. Từ chối Edit, WebFetch... không có ở D/G: dấu ngắt vẫn là ngắt.
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in s.calls and user_rejected(e, c):
                st["after_reject"] = True
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                txt = " ".join(texts_of(c.get("content"))).strip()
                words = clip(txt.split(REJECT_SAID, 1)[1]) if txt.startswith(REJECT_PREFIX) and REJECT_SAID in txt else ""
                if words:
                    add_event(s, e, path, "reject_note", doing=st["tools"].get(c.get("tool_use_id"), ""), text=words)
        return
    text = human_text(e, content)
    if text is None:
        return
    text = unicodedata.normalize("NFC", text).lstrip()
    if text.startswith(INTERRUPT_PREFIX):
        # Bấm No ở hộp hỏi thì Claude Code ghi dấu ngắt ngay sau tool_result từ chối, chưa có agent trả lời xen giữa:
        # dấu đó thuộc về lần từ chối (đã ở D/G, hoặc là từ chối kèm lời), không phải một lần ngắt.
        if not st["after_reject"]:
            add_event(s, e, path, "interrupt", doing=st["doing"])
        st["after_reject"] = False
        return
    if text.startswith(MACHINE_TAGS):
        return
    if COMMAND_TAG.match(text):
        m = re.search(r"<command-args>(.*?)</command-args>", text, re.DOTALL)
        text = m.group(1) if m else ""
    if who != "phiên chính":
        return  # tin "user" trong file subagent là lead gửi, không phải bạn gõ
    one = " ".join(text.split())
    st["after_reject"] = False  # lượt hỏi mới khép lần từ chối trước: Esc sau đó là ngắt thật
    add_event(s, e, path, "prompt", text=clip(one))  # chữ để khử trùng dòng không có uuid
    if st["assistant"] and CORRECTION_RE.search(one):
        add_event(s, e, path, "correction", text=clip(one))


def parse_entry(e, s, path, who, cutoff, only_under):
    t = e.get("type")
    msg = e.get("message") or {}
    when = ts_of(e)
    fresh = when is None or when >= cutoff
    if t == "assistant" and isinstance(msg, dict):
        track_assistant(e, msg, s, fresh)  # cả dòng cũ: câu sửa ở đầu cửa sổ --since vẫn biết agent đã trả lời trước đó
    # Khoá dòng cho mục E, F và old_entries: dòng chép sang file khác giữ uuid, đếm một lần (xem add_event). Không có uuid
    # thì mỗi dòng một khoá riêng, không gộp theo nội dung: hai lần chạy giống hệt nhau vẫn là hai lần.
    u = e.get("uuid")
    key = u if isinstance(u, str) and u else object()
    if not fresh:
        s.old_entries.add(key)
        return
    if t == "assistant":
        wire = e.get("wireToolInputs") or {}
        for c in msg.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in SHELL_TOOLS:
                inp = wire.get(c.get("id")) or c.get("input") or {}
                cmd = inp.get("command") if isinstance(inp, dict) else None
                cwd_ok = in_scope(e.get("cwd"), only_under)
                if cmd and cwd_ok:
                    s.calls[c["id"]] = {"tool": c["name"], "command": cmd, "cwd": e.get("cwd") or "",
                                        "ts": e.get("timestamp") or "", "file": str(path), "who": who,
                                        "status": "chưa rõ", "permission": None}
    elif t == "user":
        pd = e.get("permissionDecision")
        for c in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in s.calls:
                call = s.calls[c["tool_use_id"]]
                user_no = user_rejected(e, c)
                config_no = isinstance(pd, dict) and pd.get("decision") == "reject"
                call["status"] = "bị từ chối" if (user_no or config_no) else "đã chạy"
                call["rejected_by"] = "người" if user_no else ("cấu hình" if config_no else "")
                if isinstance(pd, dict):
                    call["permission"] = pd
        track_user(e, msg, s, path, who, only_under)
    elif t == "attachment":
        a = e.get("attachment") or {}
        at = a.get("type") or ""
        cmd = a.get("command") or ""
        if at.startswith("hook_") and "guard-irreversible" in cmd and a.get("toolUseID"):
            out = a.get("stdout") or ""
            m = re.search(r'"permissionDecisionReason"\s*:\s*"([^"]*)"', out)
            # Dự án tự cài kit mà máy có plugin: hai guard chạy song song, thứ tự bản ghi không cố định. Một bản hỏi là đã hỏi.
            prev = s.guard.get(a["toolUseID"])
            if not (prev and prev["asked"]):
                s.guard[a["toolUseID"]] = {"asked": '"ask"' in out, "reason": m.group(1) if m else ""}
        if at == "hook_system_message" and a.get("hookEvent") == "Stop" and \
                re.search(r"vẫn đỏ sau \d+ lần chặn", a.get("content") or ""):
            s.stop_releases.add(key)
        if at in ("hook_non_blocking_error", "hook_error") or (
                at.startswith("hook_") and a.get("exitCode") not in (None, 0, 2)):
            if ".claude/hooks/" in cmd.replace("\\", "/") or "/plugin/run-hook.sh" in cmd.replace("\\", "/"):
                s.hook_errors[key] = {"hook": a.get("hookName") or cmd, "stderr": (a.get("stderr") or "").strip(),
                                      "exit": a.get("exitCode"), "ts": e.get("timestamp") or "", "file": str(path)}
    elif t == "system" and e.get("subtype") == "stop_hook_summary":
        # Dự án tự cài kit mà máy có plugin: một lần Stop có cả bản dự án lẫn bản plugin (nhường, vài ms). Tính một lần.
        runs = [h["durationMs"] for h in e.get("hookInfos") or []
                if "stop-gate" in (h.get("command") or "") and isinstance(h.get("durationMs"), (int, float))]
        if runs:
            s.stop_runs[key] = max(runs)
        # Mỗi lần chặn có cả user isMeta "Stop hook feedback" lẫn hookErrors: chỉ đếm hookErrors.
        n = 0  # thứ tự lần chặn trong dòng
        for err in e.get("hookErrors") or []:
            if isinstance(err, str):
                for m in re.finditer(r"check\.sh đang đỏ.*?lần chặn (\d+)/(\d+)", err, re.DOTALL):
                    s.stop_blocks[key, n] = f"{m.group(1)}/{m.group(2)}"
                    n += 1
                    if in_scope(e.get("cwd"), only_under):
                        add_event(s, e, path, "stop_block")


def repo_root(cwd):
    """Thư mục cha gần nhất có .git (repo hoặc worktree); None nếu cwd không có trên máy này."""
    if not cwd:
        return None
    try:
        p = Path(cwd)
        for d in (p, *p.parents):
            if (d / ".git").exists():
                return d
    except (OSError, ValueError):
        pass
    return None


def project_name(cwd):
    """Dự án của một sự kiện: thư mục repo chứa cwd, worktree quy về repo chính. Cwd không có trên máy này
    (vd C:\\x\\y đọc trên Linux) thì tên thư mục cuối."""
    cwd = re.split(r"[\\/]\.claude[\\/]worktrees[\\/]", cwd or "", maxsplit=1)[0]  # worktree của Claude Code
    try:
        here = bool(cwd) and Path(cwd).is_absolute() and Path(cwd).exists()  # đường dẫn tương đối sẽ bị hiểu theo thư mục hiện tại
    except (OSError, ValueError):
        here = False
    r = repo_root(cwd) if here else None
    if r is not None:
        try:  # worktree git: .git là file "gitdir: <repo chính>/.git/worktrees/<tên>" (đường dẫn có thể tương đối)
            git = (r / ".git").read_text(encoding="utf-8", errors="replace") if (r / ".git").is_file() else ""
        except OSError:
            git = ""
        m = re.match(r"gitdir:\s*(.+?)[\\/]\.git[\\/]worktrees[\\/]", git)
        return (Path(os.path.normpath(r / m.group(1))).name if m else "") or r.name
    parts = [x for x in re.split(r"[\\/]+", cwd) if x]
    return parts[-1] if parts else "(không rõ)"


def weekly_rows(events, project):
    """Mục J: một dòng cho mỗi tuần ISO (giờ địa phương của máy) × dự án có sự kiện, tuần cũ trước."""
    rows = {}
    for ev in events:
        y, w = datetime.fromtimestamp(ts_of({"timestamp": ev["ts"]})).isocalendar()[:2]
        key = (f"{y}-W{w:02d}", project(ev["cwd"]))
        r = rows.setdefault(key, {"week": key[0], "project": key[1], "prompts": 0, "interrupt": 0, "reject_note": 0,
                                  "correction": 0, "stop_blocks": 0, "verifier_pass": 0, "verifier_fail": 0,
                                  "verifier_inconclusive": 0, "reviewer_blocked": 0, "reviewer_total": 0})
        k = ev["kind"]
        if k == "prompt":
            r["prompts"] += 1
        elif k in FIX_KINDS:
            r[k] += 1
        elif k == "stop_block":
            r["stop_blocks"] += 1
        elif k == "verdict" and ev["agent"] == "verifier" and "verifier_" + ev["verdict"].lower() in r:
            r["verifier_" + ev["verdict"].lower()] += 1
        elif k == "verdict" and ev["agent"] == "reviewer":
            r["reviewer_total"] += 1
            r["reviewer_blocked"] += ev["verdict"] == "CHẶN"
    for r in rows.values():
        r["fixes"] = r["interrupt"] + r["reject_note"] + r["correction"]
        r["fixes_per_10"] = round(10 * r["fixes"] / r["prompts"], 1) if r["prompts"] else None
    return [rows[k] for k in sorted(rows)]


class Context:
    """Guard và mẫu nghi ngờ áp cho một lệnh: của repo chứa cwd nếu repo đó cài kit, không thì của dự án mặc định."""

    def __init__(self, default_root):
        self.default_root = default_root
        self.cache = {}
        self.by_cwd = {}

    def kit_root(self, cwd):
        r = repo_root(cwd)
        if r is not None and ((r / ".claude" / "hooks" / "guard-irreversible.sh").is_file()
                              or (r / ".claude" / "audit-watch.txt").is_file()):
            return r
        return self.default_root

    def of(self, cwd):
        if cwd in self.by_cwd:
            return self.by_cwd[cwd]
        r = self.kit_root(cwd)
        if r not in self.cache:
            g = r / ".claude" / "hooks" / "guard-irreversible.sh" if r is not None else None
            self.cache[r] = ((g if g is not None and g.is_file() else KIT_GUARD).as_posix(),
                             SUSPICIOUS + (load_watch(r) if r is not None else []))
        self.by_cwd[cwd] = self.cache[r]
        return self.cache[r]


def find_bash():
    cand = os.environ.get("AUDIT_BASH")
    if cand and Path(cand).exists():
        return cand
    return shutil.which("bash")


def replay(guard, bash, call):
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": call["tool"], "cwd": call["cwd"],
                          "tool_input": {"command": call["command"]}})
    try:
        p = subprocess.run([bash, guard], input=payload.encode("utf-8"), capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"asked": None, "reason": "", "error": f"không chạy được guard: {exc}"}
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace").strip()
    m = re.search(r'"permissionDecisionReason"\s*:\s*"([^"]*)"', out)
    bad = p.returncode != 0 or (err and not out)
    return {"asked": None if bad else '"ask"' in out, "reason": m.group(1) if m else "",
            "error": (err or f"exit {p.returncode}") if bad else ""}


def who_approved(pd):
    if not isinstance(pd, dict):
        return "không rõ"
    src, rt = pd.get("source") or "", pd.get("reasonType") or ""
    if src.startswith("user"):
        return "người duyệt"
    if rt == "classifier":
        return "auto mode tự duyệt"
    if rt in ("rule", "mode"):
        return "luật/chế độ cho phép"
    return src or "không rõ"


def rejecter(it):
    """Ai chặn một lệnh bị từ chối: bạn ở hộp hỏi, hay một lớp bảo vệ khác (auto mode, luật deny)."""
    if it.get("rejected_by") == "người":
        return "bạn từ chối"
    rt = (it["permission"] or {}).get("reasonType") if isinstance(it["permission"], dict) else ""
    return {"classifier": "auto mode chặn", "rule": "luật deny chặn", "mode": "chế độ quyền chặn"}.get(rt, "cấu hình chặn")


def short(cmd, n=160):
    one = " ⏎ ".join(x.strip() for x in cmd.strip().splitlines())
    return one if len(one) <= n else one[: n - 1] + "…"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=".", help="thư mục dự án (mặc định: thư mục hiện tại)")
    ap.add_argument("--all", action="store_true", help="soát mọi dự án trong ~/.claude/projects (kit cài dạng plugin)")
    ap.add_argument("--transcripts", action="append", default=[], help="thư mục chứa *.jsonl (lặp được)")
    ap.add_argument("--since", type=float, default=7, help="chỉ đọc phiên sửa trong N ngày gần đây (mặc định 7)")
    ap.add_argument("--no-replay", action="store_true", help="không chạy lại guard hiện tại")
    ap.add_argument("--json", action="store_true", help="in JSON thay cho markdown")
    ap.add_argument("--out", help="ghi báo cáo ra file")
    args = ap.parse_args()

    root = Path(args.project).resolve()
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode == 0 and top.stdout.strip():
            root = Path(top.stdout.strip()).resolve()
    except OSError:
        pass
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    cutoff = time.time() - args.since * 86400
    dirs = [(Path(d), None) for d in args.transcripts]
    base = config / "projects"
    if args.all and not dirs:
        dirs = [(d, None) for d in sorted(base.iterdir()) if d.is_dir()] if base.is_dir() else [(base, None)]
    if not dirs:
        keys = {project_key(root)}
        m = re.match(r"^/([a-z])/(.*)$", str(root).replace("\\", "/"))
        if m:  # Git Bash thấy /c/x, Claude Code trên Windows ghi C:\x
            keys.add(project_key(f"{m.group(1).upper()}:\\{m.group(2)}"))
        if base.is_dir():
            for d in base.iterdir():
                if d.name in keys:
                    dirs.append((d, None))
                elif any(d.name.startswith(k + "-") for k in keys):
                    # thư mục con hoặc worktree của dự án: chỉ nhận lệnh có cwd nằm trong dự án
                    dirs.append((d, norm_path(root)))
        if not dirs:
            dirs = [(base / k, None) for k in keys]
    files = []
    for d, only in dirs:
        if d.is_dir():
            files += [(f, only) for f in d.rglob("*.jsonl") if f.stat().st_mtime >= cutoff]
    if not files:
        print(f"Không tìm thấy file phiên nào trong {', '.join(str(d) for d, _ in dirs)} "
              f"(sửa trong {args.since:g} ngày gần đây). Dùng --transcripts để chỉ thư mục khác.", file=sys.stderr)
        return 2

    s = Session()
    for f, only in sorted(files):
        parse(f, s, cutoff, only)
    ctx = Context(None if args.all else root)

    bash = find_bash()
    replayed = {}
    can_replay = bool(not args.no_replay and KIT_GUARD.is_file() and bash)
    if can_replay:
        uniq = {}
        for cid, c in s.calls.items():
            uniq.setdefault((c["tool"], c["cwd"], c["command"]), c)
        with ThreadPoolExecutor(4) as ex:
            for key, r in zip(uniq, ex.map(lambda c: replay(ctx.of(c["cwd"])[0], bash, c), uniq.values())):
                replayed[key] = r

    rows = collections.defaultdict(list)
    for cid, c in s.calls.items():
        hist = s.guard.get(cid)
        now = replayed.get((c["tool"], c["cwd"], c["command"]))
        sus = suspicious_labels(c["command"], ctx.of(c["cwd"])[1], c["tool"])
        item = dict(c, id=cid, suspicious=sus, guard_then=hist, guard_now=now, approved=who_approved(c["permission"]))
        asked_then = bool(hist and hist["asked"])
        asked_now = now["asked"] if now else None
        ran = c["status"] == "đã chạy"
        pd = c["permission"] if isinstance(c["permission"], dict) else {}
        accepted = pd.get("decision") == "accept"
        # Có hộp hỏi hay không suy từ quyết định cấp phép (luôn có trong file phiên); bản ghi kết quả
        # của guard thì có bản Claude Code không ghi (Windows 2.1.296), nên không dựa riêng vào nó.
        prompted = (pd.get("source") or "").startswith("user") or c.get("rejected_by") == "người"
        asked_eff = asked_then or (not hist and asked_now is True and prompted)
        on_main = bool(now and "đang ở nhánh" in (now.get("reason") or ""))  # guard hỏi theo nhánh, không theo chữ
        if asked_then and asked_now is False:
            rows["B"].append(item)
        if ran:
            # H và A đều cần khớp mẫu nghi ngờ (đã bỏ heredoc/chuỗi): guard so cả chữ trong dữ liệu nên hay hỏi thừa.
            if asked_now is True and not asked_eff and not prompted and (sus or on_main):
                rows["H"].append(item)
            elif asked_now is not True and not asked_then and sus:
                rows["A"].append(item)
            if asked_eff and accepted:
                rows["C"].append(item)
        elif c["status"] == "bị từ chối":
            if asked_eff or (not hist and asked_now is True):
                rows["D"].append(item)
            elif asked_now is not True:
                rows["G"].append(item)

    report = {
        "project": "mọi dự án" if args.all else str(root), "all": args.all, "transcripts": [str(d) for d in dirs], "files": len(files), "bad_lines": s.bad_lines,
        "shell_commands": len(s.calls), "replay": bool(can_replay),
        "A_possible_misses": rows["A"], "B_regressions": rows["B"], "C_asked_approved": rows["C"],
        "D_asked_rejected": rows["D"], "G_rejected_not_asked": rows["G"], "H_ran_unguarded": rows["H"],
        "hook_errors": list(s.hook_errors.values()), "old_entries_skipped": len(s.old_entries),
        "guard_records": len(s.guard),
        "replay_errors": sorted({r["error"] for r in replayed.values() if r.get("error")})[:5],
        "stop_gate": {"runs": len(s.stop_runs), "blocks": list(s.stop_blocks.values()), "released_after_max": len(s.stop_releases),
                      "median_s": round(statistics.median(s.stop_runs.values()) / 1000, 1) if s.stop_runs else None,
                      "max_s": round(max(s.stop_runs.values()) / 1000, 1) if s.stop_runs else None},
    }
    names = {}

    def project(cwd):
        if cwd not in names:
            names[cwd] = project_name(cwd)  # repo_root dò hệ thống file: mỗi cwd một lần
        return names[cwd]

    events = list(s.events.values())
    report["I_user_corrections"] = sorted((dict(ev, project=project(ev["cwd"])) for ev in events if ev["kind"] in FIX_KINDS),
                                          key=lambda ev: ts_of({"timestamp": ev["ts"]}))
    report["weekly"] = weekly_rows(events, project)
    text = json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"Đã ghi báo cáo: {args.out}")
    else:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    return 0


def reason_of(it):
    """Lý do guard hỏi: từ bản ghi lúc chạy, không có thì từ lần chạy lại guard hiện tại."""
    m = re.search(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)", (it["guard_then"] or it["guard_now"] or {}).get("reason", ""))
    return m.group(1) if m else "guard hỏi"


def render(r):
    L = [f"# Báo cáo đội agent: {r['project']}", "",
         f"Đọc {r['files']} file phiên, {r['shell_commands']} lệnh shell"
         + (f", {r['bad_lines']} dòng không đọc được" if r["bad_lines"] else "")
         + ("." if r["replay"] else ". KHÔNG chạy lại được guard hiện tại (thiếu bash hoặc guard), mục A/B/H kém tin cậy."), ""]
    if r["shell_commands"] and not r["guard_records"]:
        L += ["ℹ File phiên không có bản ghi kết quả của guard (bản Claude Code này không ghi). Mục B cần bản ghi đó nên luôn rỗng; "
              "C, D, H được suy từ việc bạn có thấy hộp hỏi hay không.", ""]
    if r["replay_errors"]:
        L += ["⚠ Chạy lại guard bị lỗi (các lệnh đó coi như chưa biết guard có hỏi không): "
              + "; ".join(f"`{x[:200]}`" for x in r["replay_errors"]), ""]

    def cmd_lines(items, extra):
        seen = set()
        for it in items:
            k = (it["tool"], it["command"], it["cwd"] if r.get("all") else "")
            if k in seen:
                continue
            seen.add(k)
            where = f" @ {it['cwd']}" if r.get("all") else ""
            L.append(f"- `{short(it['command'])}`{where}  ({it['tool']}, {it['who']}, {extra(it)})")

    sec = [
        ("A", "Có thể guard bỏ sót", "Lệnh nghi nguy hiểm đã chạy mà guard hiện tại không hỏi. Xem từng dòng: nếu là thật thì thêm ca test 'phải hỏi' rồi sửa guard.",
         lambda it: it.get("note") or f"{', '.join(it['suspicious'])}; {it['approved']}"),
        ("B", "Hồi quy của guard", "Trước đây guard hỏi, bản hiện tại cho qua. Ưu tiên sửa.",
         lambda it: f"trước: {(it['guard_then'] or {}).get('reason', '')}"),
        ("H", "Lệnh nguy hiểm đã chạy lúc guard không hỏi", "Bản guard hiện tại có hỏi, nhưng lúc lệnh chạy thì không: guard chưa nạp (thư mục chưa trust, phiên mở ở thư mục khác, matcher thiếu tool), hook lỗi, hoặc bản cũ. Kiểm tra vì sao guard không chạy lúc đó.",
         lambda it: f"nay: {(it['guard_now'] or {}).get('reason', '')}; {it['approved']}"),
        ("C", "Guard hỏi và bạn duyệt", "Ứng viên hỏi thừa. Chỉ nới guard khi chắc lệnh vô hại, và người phải đọc kỹ thay đổi đó.",
         lambda it: reason_of(it)),
        ("D", "Guard hỏi và bị từ chối", "Guard làm đúng việc. Chỉ để thống kê.",
         lambda it: f"{reason_of(it)}; {it.get('rejected_by') or ''} từ chối"),
        ("G", "Bị từ chối mà guard không hỏi", "Dòng 'bạn từ chối': bạn phải tự chặn ở hộp xin phép thường; lệnh nguy hiểm thì guard đã bỏ sót, còn nếu chỉ là đổi ý thì bỏ qua. Dòng 'auto mode chặn' hay 'luật deny chặn': một lớp bảo vệ khác đã làm việc, chỉ để thống kê.",
         lambda it: f"{rejecter(it)}; " + (", ".join(it["suspicious"]) or "không khớp mẫu nghi ngờ")),
    ]
    key = {"A": "A_possible_misses", "B": "B_regressions", "C": "C_asked_approved", "D": "D_asked_rejected",
           "G": "G_rejected_not_asked", "H": "H_ran_unguarded"}
    for code, title, hint, extra in sec:
        items = r[key[code]]
        L += [f"## {code}. {title}: {len(items)}", "", hint, ""]
        cmd_lines(items, extra)
        L.append("")
    sg = r["stop_gate"]
    L += ["## E. Stop gate", "",
          f"- Số lần chạy: {sg['runs']}" + (f", trung vị {sg['median_s']}s, lâu nhất {sg['max_s']}s" if sg["runs"] else ""),
          f"- Số lần chặn vì check đỏ: {len(sg['blocks'])}" + (f" ({', '.join(sg['blocks'][:10])})" if sg["blocks"] else ""),
          f"- Số lần nhả sau khi chặn tối đa (agent dừng khi check còn đỏ): {sg['released_after_max']}", ""]
    errs = r["hook_errors"]
    L += [f"## F. Lỗi hook của kit: {len(errs)}", ""]
    grouped = collections.Counter((e["hook"], (e["stderr"].splitlines() or [""])[0][:200]) for e in errs)
    for (hook, first), n in grouped.most_common():
        L.append(f"- {hook} ×{n}: `{first}`")
    L.append("")
    fixes = r["I_user_corrections"]
    L += [f"## I. Bạn phải sửa agent: {len(fixes)}", "",
          "Ứng viên cho /correct: mỗi dòng là một lần bạn ngắt agent, từ chối kèm lời nhắn, hoặc gõ câu sửa. "
          "Gom thành lớp lỗi; lớp nào từ 2 lần trở lên thì chạy /correct. Câu sửa dò bằng từ khoá nên có thể khớp thừa.", ""]
    label = {"interrupt": "ngắt", "reject_note": "từ chối kèm lời", "correction": "câu sửa"}
    for ev in fixes:
        when = datetime.fromtimestamp(ts_of({"timestamp": ev["ts"]})).strftime("%Y-%m-%d %H:%M")
        what = f'"{ev["text"]}"' if ev.get("text") else ""
        if ev["kind"] != "correction":
            what = (what + " " if what else "") + f"đang: `{ev.get('doing') or 'không rõ'}`"
        where = f" @ {ev['cwd']}" if r.get("all") else ""
        L.append(f"- [{label[ev['kind']]}] {when} {what}{where}")
    L += ["", "## J. Chỉ số theo tuần", "",
          "So tuần này với tuần trước. Muốn thấy xu hướng thì chạy --since 28; tuần đầu bảng có thể thiếu ngày.", ""]
    if not r["weekly"]:
        L.append("Chưa có dữ liệu.")
    else:
        L += ["| Tuần | Dự án | Lượt hỏi | Bạn sửa (ngắt/lời/câu) | Sửa trên 10 lượt | Stop gate chặn | Verifier P/F/I | Reviewer chặn/tổng |",
              "|---|---|---|---|---|---|---|---|"]
        for w in r["weekly"]:
            per10 = "-" if w["fixes_per_10"] is None else f"{w['fixes_per_10']:.1f}"
            L.append(f"| {w['week']} | {w['project']} | {w['prompts']} | {w['fixes']} ({w['interrupt']}/{w['reject_note']}/{w['correction']}) "
                     f"| {per10} | {w['stop_blocks']} | {w['verifier_pass']}/{w['verifier_fail']}/{w['verifier_inconclusive']} "
                     f"| {w['reviewer_blocked']}/{w['reviewer_total']} |")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
