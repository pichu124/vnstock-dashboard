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
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SHELL_TOOLS = ("Bash", "PowerShell")
# Guard của chính bộ kit chứa script này: dùng cho dự án không có bản guard riêng (kit cài dạng plugin).
KIT_GUARD = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard-irreversible.sh"
REJECT_PREFIX = "The user doesn't want to proceed"

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
# Xoá đệ quy chỉ được coi là vô hại khi MỌI đích nằm trong thư mục tạm/build (khớp trọn tên một thành phần).
BENIGN_NAMES = {"tmp", "temp", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
                ".ruff_cache", ".cache", "coverage", ".coverage", "htmlcov", ".venv", "venv", ".tox", ".next",
                ".turbo", ".parcel-cache", "scratchpad"}
CMD_FLAG = re.compile(r"^/[a-z]$", re.IGNORECASE)


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


def segments(cmd, tool="Bash"):
    """Các lệnh đơn trong một lệnh shell, dạng (để so mẫu, đầy đủ, thư mục cd gần nhất).

    Bản để so mẫu thay chuỗi trong nháy bằng "" (trừ bash -c '...', cmd /c "...", eval), bản đầy đủ
    giữ nguyên để biết đích thật. Biến gán trong lệnh (S=/tmp/x; rm -rf $S) được thay theo thứ tự.
    """
    body = keep_shell_heredocs(cmd)
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
        full = expand(re.sub(r"\0(\d+)\0", lambda m: store[int(m.group(1))], seg), env)
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
        out.append((plain, full, ctx))
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


def benign_delete(full, ctx):
    toks = [t.strip("\"'") for t in TOKEN.findall(full)]
    while toks and toks[0].lower() in ("sudo", "doas", "wsl", "command", "builtin"):
        toks = toks[1:]
    cmd_style = bool(toks) and toks[0].lower() in ("rd", "del", "erase", "rmdir")  # /s /q là cờ của cmd
    targets = [t for t in toks[1:] if t and not t.startswith("-") and not (cmd_style and CMD_FLAG.match(t))]
    if not targets:
        return False
    for t in targets:
        if ".." in re.split(r"[\\/]+", t):
            return False
        if benign_path(t):
            continue
        rel = not is_absolute(t)
        if rel and ctx and benign_path(ctx):
            continue
        return False
    return True


def suspicious_labels(cmd, patterns, tool="Bash"):
    labels = []
    for plain, full, ctx in segments(cmd, tool):
        for rx, label in patterns:
            if label in labels or not re.search(rx, plain, re.IGNORECASE):
                continue
            if label == "xoá đệ quy" and benign_delete(full, ctx):
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


class Session:
    def __init__(self):
        self.calls = {}        # tool_use_id -> dict
        self.guard = {}        # tool_use_id -> {"asked": bool, "reason": str}
        self.hook_errors = []  # dict
        self.stop_runs = []    # ms
        self.stop_blocks = []  # "1/3"
        self.stop_releases = 0
        self.bad_lines = 0
        self.old_entries = 0


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
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
                if isinstance(e, dict):
                    parse_entry(e, s, path, who, cutoff, only_under)
            except (ValueError, AttributeError, TypeError, KeyError):
                s.bad_lines += 1  # JSON hỏng hoặc sai hình dạng: đếm, không làm hỏng cả lượt


def parse_entry(e, s, path, who, cutoff, only_under):
    t = e.get("type")
    msg = e.get("message") or {}
    when = ts_of(e)
    if when is not None and when < cutoff:
        s.old_entries += 1
        return
    if t == "assistant":
        wire = e.get("wireToolInputs") or {}
        for c in msg.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in SHELL_TOOLS:
                inp = wire.get(c.get("id")) or c.get("input") or {}
                cmd = inp.get("command") if isinstance(inp, dict) else None
                cwd_ok = only_under is None or (norm_path(e.get("cwd") or "") + "/").startswith(only_under + "/")
                if cmd and cwd_ok:
                    s.calls[c["id"]] = {"tool": c["name"], "command": cmd, "cwd": e.get("cwd") or "",
                                        "ts": e.get("timestamp") or "", "file": str(path), "who": who,
                                        "status": "chưa rõ", "permission": None}
    elif t == "user":
        pd = e.get("permissionDecision")
        for c in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in s.calls:
                call = s.calls[c["tool_use_id"]]
                txt = " ".join(texts_of(c.get("content"))).strip()
                user_no = e.get("toolUseResult") == "User rejected tool use" or (
                    c.get("is_error") and txt.startswith(REJECT_PREFIX))
                config_no = isinstance(pd, dict) and pd.get("decision") == "reject"
                call["status"] = "bị từ chối" if (user_no or config_no) else "đã chạy"
                call["rejected_by"] = "người" if user_no else ("cấu hình" if config_no else "")
                if isinstance(pd, dict):
                    call["permission"] = pd
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
            s.stop_releases += 1
        if at in ("hook_non_blocking_error", "hook_error") or (
                at.startswith("hook_") and a.get("exitCode") not in (None, 0, 2)):
            if ".claude/hooks/" in cmd.replace("\\", "/") or "/plugin/run-hook.sh" in cmd.replace("\\", "/"):
                s.hook_errors.append({"hook": a.get("hookName") or cmd, "stderr": (a.get("stderr") or "").strip(),
                                      "exit": a.get("exitCode"), "ts": e.get("timestamp") or "", "file": str(path)})
    elif t == "system" and e.get("subtype") == "stop_hook_summary":
        # Dự án tự cài kit mà máy có plugin: một lần Stop có cả bản dự án lẫn bản plugin (nhường, vài ms). Tính một lần.
        runs = [h["durationMs"] for h in e.get("hookInfos") or []
                if "stop-gate" in (h.get("command") or "") and isinstance(h.get("durationMs"), (int, float))]
        if runs:
            s.stop_runs.append(max(runs))
        # Mỗi lần chặn có cả user isMeta "Stop hook feedback" lẫn hookErrors: chỉ đếm hookErrors.
        for err in e.get("hookErrors") or []:
            if isinstance(err, str):
                for m in re.finditer(r"check\.sh đang đỏ.*?lần chặn (\d+)/(\d+)", err, re.DOTALL):
                    s.stop_blocks.append(f"{m.group(1)}/{m.group(2)}")


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
        "hook_errors": s.hook_errors, "old_entries_skipped": s.old_entries,
        "guard_records": len(s.guard),
        "replay_errors": sorted({r["error"] for r in replayed.values() if r.get("error")})[:5],
        "stop_gate": {"runs": len(s.stop_runs), "blocks": s.stop_blocks, "released_after_max": s.stop_releases,
                      "median_s": round(statistics.median(s.stop_runs) / 1000, 1) if s.stop_runs else None,
                      "max_s": round(max(s.stop_runs) / 1000, 1) if s.stop_runs else None},
    }
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
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
