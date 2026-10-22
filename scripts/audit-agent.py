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
import itertools
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
    # Chỉ xét `git` đầu tiên của dòng (lookahead + \1 thay nhóm nguyên tử, không thử lại `git` sau): `\bgit\b.*\bfilter-…`
    # quét `.*` tới cuối dòng từ mỗi `git`, bậc hai. Vẫn khớp đúng những chuỗi như mẫu đó: `.` không qua `\n`, và `git` nào
    # có filter-… phía sau trên dòng thì `git` đầu dòng cũng có.
    (r"(?m)^(?=(.*?\bgit\b))\1.*\bfilter-(branch|repo)\b", "viết lại lịch sử git"),
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


# Heredoc: dòng mở (rest: phần còn lại của dòng, vẫn là lệnh; cont: `\` lẻ cuối dòng), thân, dòng đóng (lỏng: khoảng trắng
# hai bên). Chưa đóng thì thân tới hết chuỗi như bash. HEREDOC nhận thân rỗng khi dòng ngay sau dòng mở đúng là dấu đóng như
# bash đòi (chỉ `<<-` cho tab đầu dòng, không khoảng trắng nào khác) và dòng mở không có `\` lẻ cuối (bash nối dòng đó vào
# lệnh thành tham số, không phải dấu đóng): không có nhóm body. HEREDOC_6F32D5A không nhận thân rỗng như 6f32d5a: cách đọc
# scoped=False dùng nó, cách đọc scoped dùng thêm khi hai regex khác nhau trên lệnh (empty_body=False), để phép hợp trong
# suspicious_labels vẫn có mọi nhãn các cách đọc cũ cho. Lookahead `[^\n]*\n` trước rest không đổi match, chỉ để `<<NAME` trên
# dòng không có `\n` thất bại nhanh: nhóm của rest quét lại cả dòng ở mỗi lần thử chậm hơn cỡ trăm lần.
_HD_OPEN = r"<<(?P<dash>-)?\s*(?P<q>['\"]?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P=q)(?=[^\n]*\n)(?P<rest>(?:[^\n\\]|\\[^\n])*(?P<cont>\\)?)\n"
_HD_BODY = r"(?P<body>.*?)(?:\n[ \t]*(?P=name)[ \t]*(?:\n|$)|\Z)"
HEREDOC = re.compile(_HD_OPEN + r"(?:(?(cont)(?!))(?(dash)\t*)(?P=name)(?:\n|$)|" + _HD_BODY + ")", re.DOTALL)
HEREDOC_6F32D5A = re.compile(_HD_OPEN + _HD_BODY, re.DOTALL)
# segments(strict=True): thân rỗng khi dòng ngay sau dòng mở là dòng đóng (`cat <<'EOF'⏎EOF⏎rm -rf src`), đóng lỏng như
# thân không rỗng (khoảng trắng hai bên, cả khi dòng mở có `\` lẻ cuối). Thân không rỗng kèm `\n` cuối (thành một đoạn
# rỗng). Dòng mở ở cuối lệnh, không `\n`, khớp với thân rỗng. `<<` sau `<` là here-string `<<<`, không mở heredoc: HEREDOC
# lấy các dòng sau `cat <<< EOF` làm thân.
HEREDOC_STRICT = re.compile(r"(?<!<)<<-?\s*(?P<q>['\"]?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P=q)(?P<rest>[^\n]*)(?:\n|$)"
                            r"(?P<body>.*?)(?:(?<=\n)[ \t]*(?P=name)[ \t]*(?:\n|$)|\Z)", re.DOTALL)
# keep_shell_heredocs(bash=True), port vibrant-pascal 970114a: tên heredoc là cả một từ shell (`EOF-PY`, `E"O"F`, `'E-X'`,
# `<<\EOF`, `$'E'`, `$'\x45'`, `$"E"`, `E\`⏎`F` nối dòng, `EOF\r`, tên mở bằng chữ số: bash chỉ tách từ ở dấu cách, tab,
# xuống dòng): có phần trong nháy hay sau `\` thì thân không được thay biến, dòng đóng đúng bằng tên đã bỏ nháy (UNQUOTE_X,
# `$'…'` giải mã như bash: ansi_c; `<<-`: bỏ tab đầu). Từ dừng ở chỗ không phải dấu tách (nháy chưa đóng) hay tên nhiều
# dòng thì không đọc là heredoc; `<<` khi số học đang mở (`$((1<<n))`, `$[1<<n]`: ARITH_X) là dịch bit.
HEREDOC_X = re.compile(r"(?<!<)<<(?!<)(?P<tab>-)?[ \t]*(?P<word>(?:[^ \t\n;&|()<>\\\"'$]|\$(?!')|\\[\s\S]"
                       r"|\$'(?:[^'\\]|\\[\s\S])*'|\"(?:[^\"\\]|\\[\s\S])*\"|'[^']*')+)")
# Phần có nháy của một từ: `\x`, $'…', '…', "…", $"…" (trong "…" chỉ `\` trước $ ` " \ là thoát); `\` + xuống dòng
# (nối dòng, cả trong "…") bị bỏ.
UNQUOTE_X = re.compile(r"\\(.)|\\\n|\$'((?:[^'\\]|\\[\s\S])*)'|'([^']*)'|\$?\"((?:[^\"\\]|\\[\s\S])*)\"")
# Ký tự thoát trong $'…' (ansi_c): \a…\v, \\ \' \" \?, bát phân 1–3 chữ số, \xH(H), \uH…(4), \UH…(8), \c; `\`
# trước chữ khác giữ nguyên như bash.
ANSI_C_X = re.compile(r"\\(?:([abeEfnrtv])|([\\'\"?])|([0-7]{1,3})|x([0-9A-Fa-f]{1,2})|u([0-9A-Fa-f]{1,4})"
                      r"|U([0-9A-Fa-f]{1,8})|c)")
# Số học đang mở ở `<<` của HEREDOC_X: `$((`, `((` đóng bằng `))`; `$[` đóng bằng `]` (đếm cả `[…]` lồng bên trong).
# Phần trong nháy (chưa đóng thì tới hết lệnh), comment, ký tự thoát là một khớp riêng, không đếm (`echo "(("`,
# `echo '))'`); `<<` nằm trong một khớp như vậy (`let 'x=1<<2'`, `# a<<b`, `\<<E`) không phải toán tử heredoc.
ARITH_X = re.compile(r"\\[\s\S]|\$'(?:[^'\\]|\\[\s\S])*(?:'|\Z)|\"(?:[^\"\\]|\\[\s\S])*(?:\"|\Z)|'[^']*(?:'|\Z)"
                     r"|(?:^|[\s;&|()<>])#[^\n]*|(?P<dp>\$?\(\()|(?P<dc>\)\))|(?P<bo>\$\[)|(?P<b>[\[\]])", re.MULTILINE)
# Here-string `<<<` (keep_shell_heredocs(bash=True)): từ sau toán tử. Đưa vào shell (`bash <<< 'rm -rf src'`, `cat <<< …
# | bash`) thì chuỗi là lệnh, như thân heredoc.
HERESTR_X = re.compile(r"<<<[ \t]*(\$'(?:[^'\\]|\\[\s\S])*'|'[^']*'|\"(?:[^\"\\]|\\[\s\S])*\"|(?:[^\s;&|()<>\\'\"]|\\[\s\S])+)")
PIPE_SHELL = re.compile(r"^\s*\|\s*(bash|sh|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b", re.IGNORECASE)
# here_strings: tên shell ở đâu đó trong đoạn (như SHELL_WORD, đoạn đã cắt ở `|;&` và xuống dòng), `| shell` ngay sau từ.
SHELL_WORD_ANY = re.compile(r"\b(bash|sh|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b", re.IGNORECASE)
HS_PIPE_SHELL = re.compile(r"[ \t]*\|[ \t]*(bash|sh|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b", re.IGNORECASE)
SHELL_WORD = re.compile(r"\b(bash|sh|zsh|dash|pwsh|powershell|cmd)(\.exe)?\b[^\n|;&]*$", re.IGNORECASE)
SPLIT = re.compile(r"\n|;|&&|\|\||\|")
LINE_JOIN = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")  # `\` + xuống dòng mà `\` không bị thoát (`\\`); thay bằng r"\1" là nối dòng
# Dòng dấu mở thân heredoc đưa vào shell (OPEN: <<EOF, shell cha thay biến trong thân; OPEN_RAW: <<'EOF', không thay) và
# dòng dấu đóng (keep_shell_heredocs). Khác \0 của kho chuỗi trong nháy. NOT_LAST theo sau dấu mở khi trên dòng mở, sau
# toán tử heredoc, còn lệnh (`bash <<'EOF' && cd x && bash`): shell nhận thân không phải lệnh cuối dòng. SNAP đánh dấu chỗ
# toán tử heredoc trên dòng mở: env của thân chụp tại đó, trước lệnh sau toán tử (segments, cách đọc parent_env và strict).
OPEN, OPEN_RAW, CLOSE, NOT_LAST, SNAP = "\x02", "\x03", "\x01", "\x04", "\x05"
# segments(strict=True) dời SNAP từ chỗ toán tử tới cuối lệnh chứa toán tử: trước `;`, `&&`, `|`, `&` chạy nền (không phải
# `&>`, `>&`), xuống dòng hay chuỗi `\` không có chữ theo sau. Cùng đoạn nên env chụp vẫn vậy, nhưng SNAP không chen giữa
# shell và cờ (`bash <<EOF +e -c '…'`: SHELL_C, SHELL_C_BODY_STRICT vẫn khớp) hay ngay trước `#`, và `\` trước xuống dòng
# còn nguyên cho LINE_JOIN. Phần trước SNAP là lệnh nhận thân cùng các lệnh chạy nền trước nó: gán tạm của lệnh đó vào env
# của shell con, phép gán sau `&` (`bash <<EOF & D=x`) chạy sau khi shell con đã tách ra thì không.
SNAP_END = re.compile(SNAP + r"((?:[^\n;&|\\]|(?<=[<>])&|&(?=>)|\\+(?=[^\n;&|\\]))*)(?=(\n|$)?)")
# Lệnh nhận thân heredoc là chính shell cục bộ: thân chạy ở thư mục của nó. Không nhận `ssh h bash`, `env -C / bash`...
LOCAL_SHELL = re.compile(r"^(bash|sh|zsh|dash)(\s+-\w+)*\s*$")
# Cờ trước -c không được đúng là tên shell (`-bash`): không thì lần khớp từ mỗi shell trong `bash -bash -bash …` quét lại
# chuỗi cờ tới cuối, bậc hai. Vẫn khớp đúng những chuỗi như khi không chặn: lần khớp đi qua cờ `-<shell>` thì từ cờ
# `-<shell>` cuối cùng cũng khớp (sau `-` là `\b`, sau tên là khoảng trắng, các cờ sau không là shell). Cờ `-\w+` không
# chứa `.exe`; lookahead và chỗ mở cùng IGNORECASE (cả ſ). Chuỗi cờ quét từ các shell khác nhau rời nhau: tuyến tính.
SHELL_C = re.compile(r"\b(bash|sh|zsh|dash|pwsh|powershell)(\.exe)?\s+(-(?!(?:bash|sh|zsh|dash|pwsh|powershell)\s)\w+\s+)*"
                     r"-c(ommand)?\s|\bcmd(\.exe)?\s+(/\w\s+)*/[ck]\s|\beval\s"
                     r"|\|\s*(bash|sh|zsh|dash|pwsh|powershell)(\.exe)?\b",
                     re.IGNORECASE)
# Chuỗi trong nháy, hoặc comment: `#` đầu từ ngoài nháy (sau đầu chuỗi, xuống dòng, hay sau khoảng trắng, `;&|()<>` không
# thoát bằng `\`, của PowerShell là backtick) tới hết dòng. Quét chung một lượt trái→phải để nháy trong comment (`# don't`)
# không mở chuỗi nuốt các dòng sau. Cách che như 6f32d5a (không biết comment, segments(comments=False)) vẫn ở trong phép hợp:
# nó cho cả nhãn chỉ có nhờ nháy ghép sai (`true | cd /tmp/x && rm -rf y #'⏎cat <<'EOF' \⏎# don't $x⏎EOF`: bash xoá ./y).
QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'|(?<![^ \t\n;&|()<>])(?<!\\[ \t;&|()<>])#[^\n]*")
QUOTED_PS = re.compile(r"\"[^\"]*\"|'[^']*'|(?<![^ \t\n;&|()<>])(?<!`[ \t;&|()<>])#[^\n]*")  # không escape bằng \ ("C:\x\" trọn)
QUOTED_6F32D5A = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
QUOTED_PS_6F32D5A = re.compile(r"\"[^\"]*\"|'[^']*'")
# segments(exact=True) che nháy như 6f32d5a và che cả comment như một chuỗi (cất vào kho như chuỗi trong nháy): `#` mở một
# từ (sau khoảng trắng, `;&|()` hay đầu dòng, ngoài nháy) tới hết dòng. Nháy lẻ trong comment (`# don't`) không còn ghép
# với nháy của lệnh sau thành một chuỗi nuốt lệnh.
COMMENT = r"|(?:(?<=[\s;&|()])|^)#[^\n]*"
QUOTED_X = re.compile(QUOTED_6F32D5A.pattern + COMMENT, re.MULTILINE)
QUOTED_PS_X = re.compile(QUOTED_PS_6F32D5A.pattern + COMMENT, re.MULTILINE)
# segments(strict=True) của bash: `\` ngoài nháy thoát ký tự sau (`echo it\'s`), khớp trước để nháy đó không mở một chuỗi
# ghép với nháy của lệnh sau. `\` + xuống dòng không khớp (`.` không qua `\n`): cách đọc không nối dòng vẫn tách ở đó.
# Nháy ANSI-C `$'…'` khớp trước cả hai: `\'` bên trong là nháy thoát, không đóng chuỗi (`echo $'it\'s'; rm -rf src 'x'`).
QUOTED_XB = re.compile(r"\$'(?:[^'\\]|\\.)*'|\\.|" + QUOTED_X.pattern, re.MULTILINE)
# Thân -c cho segments(exact=True) gỡ ra: shell, các cờ, một cụm cờ có chữ c (-c, -lc, -ec), `--` nếu có, rồi chuỗi nháy
# đơn hay kép. Shell mở ở mọi chỗ `\b` của 96f49a6 nhận, cả sau `-` (`git-bash`, `-bash`). Cờ trước cụm c: `-x`,
# `--tên`, cụm kết thúc bằng o kèm tên (`-o pipefail`, `+O extglob`, `-euo pipefail`). Tên mở bằng `\w`, không bằng `-`:
# `-o -o …` chỉ tách được một cách, không backtrack mũ. Không `-` nào trong cờ đứng ngay trước shell + khoảng trắng, tên
# không là shell: lần khớp từ một shell không đi qua chỗ một shell khác mở (`bash -o bash -o …`, `--bash --bash …`,
# `--x-bash …` quét lại tới cuối từ mỗi shell: bậc hai), thân vẫn được gỡ từ shell sau. Cụm c tìm chữ c bằng lookahead
# rồi lấy trọn cụm: `[A-Za-z]*c[A-Za-z]*` backtrack bậc hai trên cụm dài nhiều chữ c.
SHELL_C_BODY = re.compile(r"(?<!\w)((?:bash|sh|zsh|dash)(?:\.exe)?)"
                          r"(?:\s+(?:--?(?!(?:bash|sh|zsh|dash)\s)\w(?:\w|-(?!(?:bash|sh|zsh|dash)\s))*"
                          r"|[-+][A-Za-z]*o\s+(?!(?:bash|sh|zsh|dash)\b)\w+))*?"
                          r"\s+-(?=[A-Za-z]*c)[A-Za-z]+(?:\s+--)?\s+('[^']*'|\"(?:[^\"\\]|\\.)*\")", re.IGNORECASE)
# Thân -c cho segments(strict=True) gỡ ra: shell, các cờ, một cụm cờ có chữ c (-c, -lc, +c, -co pipefail), các cờ, `--` hay
# `-` lẻ nếu có, rồi chuỗi nháy đơn, kép hay ANSI-C `$'…'`. Shell mở ở mọi chỗ `\b` của 96f49a6 nhận, cả sau `-`
# (`git-bash`, `-bash`). Cờ: `-x`, `+e`,
# `--tên`, cụm kết thúc bằng o kèm tên (`-o pipefail`, `+O extglob`, `-euo pipefail`, `-o 'pipefail'`), `--rcfile`/
# `--init-file` kèm tham số. Cụm c là token giống cụm c đầu tiên như bash đọc (có o thì thử kèm tên trước); cờ trước nó
# không được giống cụm c, không thì `bash -c -c …` (không thân) thử cụm c ở từng `-c` rồi quét tới cuối, bậc hai. Cờ kèm tên
# thử trước cờ trơn: ngược lại `'pipefail'` của `-c -o 'pipefail' '…'` thành thân. Tên mở bằng `\w` hay nháy, tham số không
# mở bằng `-`/`+`: `-o -o …`, `--rcfile --rcfile …` chỉ tách được một cách, không backtrack mũ. Không cờ, tên hay tham số nào
# đi qua chỗ một shell khác mở (không `-` hay ký tự không phải chữ nào đứng ngay trước shell + khoảng trắng, tên không là
# shell, trong nháy không có khoảng trắng): lần khớp từ một shell không quét lại tới cuối qua các shell sau (`bash -o bash
# -o …`, `--x-bash …`, `--rcfile /bash …`: bậc hai), thân vẫn được gỡ từ shell sau. Cụm c tìm chữ c bằng lookahead rồi lấy
# trọn cụm: `[A-Za-z]*c[A-Za-z]*` backtrack bậc hai trên cụm dài nhiều chữ c. Cách đọc exact giữ SHELL_C_BODY (regex của
# 1667825): sửa nó tại chỗ từng làm lệnh lồng (`bash … -c "… sh -c '…'"`) mất nhãn.
_SH = r"(?:bash|sh|zsh|dash)"
_NOT_SH = rf"(?!{_SH}(?:\.exe)?\s)"
_WORD = rf"\w(?:\w|-(?!{_SH}\s))*"
_QUOTED = r"(?:'[^'\s]*'|\"[^\"\s]*\")"
_NAME = rf"(?:(?!{_SH}\b){_WORD}|{_QUOTED})"
_ARG = rf"(?:(?![-+]){_NOT_SH}(?:\w|[^\s\w'\"]{_NOT_SH})+|{_QUOTED})"
_FLAG = rf"(?:[-+][A-Za-z]*o\s+{_NAME}|--(?:rcfile|init-file)\s+{_ARG}|(?:--?|\+)(?!{_SH}\s){_WORD})"
_C = r"[-+](?=[A-Za-z]*c)"
SHELL_C_BODY_STRICT = re.compile(rf"(?<!\w)({_SH}(?:\.exe)?)(?:\s+(?!{_C}[A-Za-z]+\s){_FLAG})*?"
                                 rf"\s+{_C}(?:(?=[A-Za-z]*o)[A-Za-z]+\s+{_NAME}|[A-Za-z]+)(?:\s+{_FLAG})*?"
                                 rf"(?:\s+--?)?\s+('[^']*'|\"(?:[^\"\\]|\\.)*\"|\$'(?:[^'\\]|\\.)*')", re.IGNORECASE)
ASSIGN = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)")
ASSIGN_EMPTY = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S*)")  # pure: `D=` gán rỗng (73226cf)
# Đoạn (đã che nháy, bỏ comment) đổi biến của shell: toàn từ NAME=VALUE, hay lệnh export/declare/typeset/local/readonly.
ASSIGN_STMT = re.compile(r"^(?:export|declare|typeset|local|readonly)(?:\s|$)|^(?:[A-Za-z_][A-Za-z0-9_]*=\S*(?:\s+|$))+$")
# segments(strict=True): lệnh gán biến mà ASSIGN không thấy. read, mapfile, readarray, getopts, local, for, printf -v, wait -p
# gán các tên trong đoạn, kể cả tên dính redirection, trong nháy hay dính cờ (`read D<f`, `printf -v "D" /`, `printf -vD /`):
# không biết giá trị. unset (trừ -f) làm biến rỗng. eval, source, `.` đầu lệnh (cả sau gán tạm `x=1 . ./e.sh`) chạy mã bất
# kỳ: không biết biến nào.
SETS_NAMES = {"read", "mapfile", "readarray", "getopts", "local", "for"}
EVAL = re.compile(r"(?<![\w-])(?:eval|source)(?![\w-])"
                  r"|^(?:[({!]\s*|(?:[A-Za-z_]\w*=\S*|if|then|do|else|elif|while|until|builtin|command|time)\s+)*"
                  r"\.(?=\s|$)")
IDENT = re.compile(r"[A-Za-z_]\w*")
# segments(pure=True): đoạn (đã che nháy, bỏ comment cuối) là phép gán thuần: toàn từ NAME=VALUE, hay export/declare/
# typeset/readonly không cờ, chỉ kèm NAME hay NAME=VALUE (`export D` giữ giá trị). `local` ngoài hàm lỗi, trong hàm chỉ
# gán trong hàm: không thuần.
PURE_STMT = re.compile(r"^(?:(?:export|declare|typeset|readonly)(?:\s+[A-Za-z_][A-Za-z0-9_]*(?:=\S*)?)*"
                       r"|(?:[A-Za-z_][A-Za-z0-9_]*=\S*(?:\s+|$))+)\s*$")
# Lệnh ghép (if, while, until, for, select, case, nhóm và thân hàm `{ }`): thân có thể không chạy hay chạy nhiều lần. Từ mở
# đứng riêng được đếm ở mọi chỗ trong đoạn (bash nhận cả `true &if`, `$(if`, `if(`, `f(){`; đếm thừa chỉ làm thêm biến thành
# không biết), từ đóng chỉ ở đầu đoạn (port blissful-dirac 5b32600).
COMPOUND_OPEN = re.compile(r"(?<![^\s&()`'\"])(?:if|while|until|for|select|case|\{)(?![^\s&|;()<>])")
COMPOUND_CLOSE = re.compile(r"(?:fi|done|esac|\})(?![^\s&|;()<>`])")
# Tên hàm không chứa `{`, `}`: chuỗi ngoặc dài không làm regex quay lui bậc hai.
FUNC_DEF = re.compile(r"(?:^|[\s;&|(){}])(?:function\s+([^\s(){}<>&|;'\"=$`]+)|([^\s(){}<>&|;'\"=$`]+)\s*\(\s*\))")
# Lệnh nhận tên biến dính cờ (`read -aD`, `printf -vD`, `wait -pD`, `declare -nD`...).
NAME_FLAGS = {"read", "mapfile", "readarray", "printf", "wait", "declare", "typeset", "local", "export", "readonly"}
CD = re.compile(r"^(cd|pushd|set-location|sl|push-location)\s+(.+)$", re.IGNORECASE)
# cd có đúng MỘT đích (bản đã che nháy): không cờ, không nhiều tham số, không `&` (chạy nền ở shell con).
CD_WORD = re.compile(r"^(cd|pushd|set-location|sl|push-location)\s+[^\s&-][^\s&]*\s*$", re.IGNORECASE)
CHDIR_NAMES = r"cd|pushd|popd|chdir|set-location|sl|push-location|pop-location|source"  # chdir: builtin của zsh
# Lệnh đổi thư mục ở vị trí lệnh bất kỳ trong đoạn (`builtin cd`, `time cd`, `FOO=1 cd`, `source`), hoặc `.` đầu lệnh.
CHDIR = re.compile(r"(?:^|[\s({!`;&|\\\"'])(?:" + CHDIR_NAMES + r")"
                   r"(?=[\s;&|(){}<>`\"']|$)"
                   r"|^(?:[({!`]\s*|(?:[A-Za-z_]\w*=\S*|builtin|command|time|-p|if|then|do|else|elif|while|until)\s+)*\.(?=\s|$)",
                   re.IGNORECASE)
# `&` chạy nền còn lệnh theo sau trong cùng đoạn (dò trên bản đã che nháy). Không phải `>&`, `<&`, `&>`; `&&` đã tách,
# `&` đầu đoạn là của `|&`.
BACKGROUND = re.compile(r"[^<>|&]&(?![>&])\s*\S")
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
    if "$" not in text:  # không có chỗ nào để thay: khỏi duyệt env (vài nghìn biến, mỗi đoạn một lượt)
        return text
    for name, val in env.items():
        # Regex chứa đúng chuỗi tên nên không khớp khi tên vắng trong text (đã thay ở các vòng trước): bỏ qua, khỏi dịch lại
        # regex cho mọi biến của env (quá 512 tên thì bộ đệm của `re` không giữ nổi).
        if name in text:
            text = re.sub(r"\$\{?" + name + r"\b\}?", lambda _m, v=val: v, text)
    return text


def expand_body(text, outer, inner):
    """Thay biến trong một đoạn của thân <<EOF không nháy như bash: `$X` shell cha thay bằng outer (env tại toán tử
    heredoc); `\\$X` (số `\\` lẻ) shell cha để lại `$X` cho shell con thay bằng inner (env của shell con, đã có phép gán trong
    thân). Các `\\\\` đứng ngay trước `\\$` bỏ cùng nó: coi như shell con vẫn thay (thừa thì chỉ báo thừa)."""
    parts = re.split(r"(?<!\\)(?:\\\\)*\\\$", text)
    out = expand(parts[0], outer)
    for x in parts[1:]:
        m = re.match(r"\{?([A-Za-z_][A-Za-z0-9_]*)\b\}?", x)  # cùng dạng tên mà expand thay
        out += inner[m[1]] + expand(x[m.end():], outer) if m and m[1] in inner else "$" + expand(x, outer)
    return out


def ansi_c(e):
    """Một ký tự thoát của $'…' (ANSI_C_X) như bash. Chỗ không chắc (NUL mà bash cắt chuỗi ở đó, ngoài ASCII tuỳ locale,
    \\cX) thành xuống dòng: tên heredoc nhiều dòng thì keep_shell_heredocs không đọc là heredoc (port 970114a)."""
    if e[1] or e[2]:
        return e[2] or "\a\b\x1b\x1b\f\n\r\t\v"["abeEfnrtv".index(e[1])]
    n = int(e[3], 8) if e[3] else int(e[4] or e[5] or e[6] or "0", 16)
    return chr(n) if 0 < n < 0x80 else "\n"


def command_subs(body):
    """Lệnh lồng `$(…)` (tới `)` đầu tiên) và `…` trong thân dữ liệu không nháy, quét một lượt (tuyến tính)."""
    out, start, tick = [], None, None
    for t in re.finditer(r"\\[\s\S]|\$\(|\)|`", body):
        if t[0] == "`" and start is None:
            if tick is None:
                tick = t.end()
            else:
                out.append(body[tick:t.start()])
                tick = None
        elif t[0] == "$(" and start is None and tick is None:
            start = t.end()
        elif t[0] == ")" and start is not None:
            out.append(body[start:t.start()])
            start = None
    return out


def keep_shell_heredocs(cmd, join=False, scoped=True, raw_marks=False, empty_body=True, exact=False, snap=False,
                        strict=False, bash=False):
    """Thân heredoc là dữ liệu, trừ khi nó được đưa vào một shell (bash <<'X' ... X): khi đó là lệnh, đặt giữa dòng OPEN
    và dòng CLOSE. join: `\\` lẻ cuối dòng mở kéo dòng kế của thân vào lệnh như bash, thân bắt đầu sau đó.
    scoped=False: như 6f32d5a, thân đặt ngay sau dòng mở, không dấu, không kéo dòng, không nhận thân rỗng.
    raw_marks: như 695e799, byte dấu có sẵn trong lệnh giữ nguyên (đọc thành dấu), không đặt SNAP.
    snap (cách đọc parent_env, strict): SNAP thay chỗ toán tử trên dòng mở. Cách đọc khác không đặt: SNAP chen giữa shell và
    cờ (`bash <<EOF -c '…'`) làm SHELL_C, SHELL_C_BODY không còn khớp; strict dời nó tới cuối đoạn (snap_to_end).
    empty_body=False: không nhận thân rỗng (HEREDOC_6F32D5A), cả khi scoped.
    exact: phần trước `<<` là dòng logic, gồm cả các dòng trước kết thúc bằng `\\` lẻ mà bash nối vào (`bash \\⏎<<'EOF'`,
    `bash \\⏎  -s <<'EOF'`: bash nhận thân). Cả khi không join: cách đọc đó để `\\` cuối comment là chữ, và comment trong
    thân (`bash \\⏎<<'EOF'⏎# x \\⏎rm -rf src`) cần cả hai cùng lúc. Cách khác chỉ xét dòng vật lý chứa `<<`.
    strict: heredoc theo HEREDOC_STRICT (thân rỗng đóng lỏng, `<<<` không mở heredoc), thay cho HEREDOC và empty_body.
    bash (dùng với strict, port vibrant-pascal 970114a): nhận heredoc như bash, thay cho HEREDOC_STRICT: tên là cả từ shell
    (HEREDOC_X), dòng đóng đúng bằng tên đã bỏ nháy, `<<` trong nháy, comment, sau `\\` hay khi số học đang mở (ARITH_X)
    không mở heredoc. Thân dữ liệu không nháy: shell cha vẫn chạy lệnh lồng `$(…)`, `…` trong đó, mỗi lệnh thành một dòng
    `( … )` (shell con). Here-string `<<<` đưa vào shell (`bash <<< 'rm -rf src'`, `cat <<< … | bash`): chuỗi là thân."""
    def sub(m):
        return place(m.string, m.start(), m["rest"], m["body"], m["q"])

    def place(string, start, rest, body, quoted):
        line_start = string.rfind("\n", 0, start) + 1
        while exact and line_start:  # dòng trước kết thúc bằng số lẻ `\`: bash nối nó với dòng đang xét
            prev_start = string.rfind("\n", 0, line_start - 1) + 1
            prev = string[prev_start:line_start - 1]
            if (len(prev) - len(prev.rstrip("\\"))) % 2 == 0:
                break
            line_start = prev_start
        body = body or ""  # rest: phần còn lại của dòng mở heredoc vẫn là lệnh: `; git ...`, `| bash`
        # Kéo dòng theo chỉ số rồi ghép một lần: cắt chuỗi mỗi vòng là bậc hai theo số dòng. `\` lẻ đã bỏ trước khi ghép
        # dòng kế, nên số `\` cuối cả lệnh cùng chẵn lẻ với số `\` cuối dòng vừa kéo.
        parts, pos = [rest], 0
        while scoped and join and pos < len(body) and re.search(r"(?<!\\)(\\\\)*\\$", parts[-1]):
            end = body.find("\n", pos)
            end = len(body) if end < 0 else end
            parts[-1] = parts[-1][:-1]
            parts.append(body[pos:end])
            pos = end + 1
        rest, body = "".join(parts), body[pos:]
        lead = string[line_start:start]
        fed = SHELL_WORD.search(LINE_JOIN.sub(r"\1", lead) if exact else lead) or PIPE_SHELL.match(rest)
        if bash and not (fed or quoted):
            return rest + "\n" + "".join("(%s)\n" % c for c in command_subs(body))
        if not (fed and scoped):
            return rest + "\n" + (body + "\n" if fed else "")
        mark = SNAP if snap and not raw_marks else ""
        return "\n".join((mark + rest, (OPEN_RAW if quoted else OPEN) + (NOT_LAST if rest.strip() else ""), body, CLOSE, ""))
    if scoped and not raw_marks:  # byte dấu có sẵn trong lệnh là chữ thường với bash: đổi thành ký tự trung tính
        cmd = re.sub("[" + OPEN + OPEN_RAW + CLOSE + NOT_LAST + SNAP + "]", "\ufffd", cmd)
    if not (bash and scoped):
        return (HEREDOC_STRICT if strict else HEREDOC if scoped and empty_body else HEREDOC_6F32D5A).sub(sub, cmd)
    cmd = here_strings(cmd)
    out, pos, dp, bk, last, toks, m = [], 0, 0, 0, None, ARITH_X.finditer(cmd), HEREDOC_X.search(cmd)
    tok = next(toks, None)
    while m:  # thân tới dòng đúng bằng tên đã bỏ nháy (có thể rỗng), không có thì tới hết lệnh
        # Số học mở tới `<<`: đếm tiếp từ chỗ trước (không đếm lại: bậc hai), không âm (`))` thừa), không về 0 ở xuống
        # dòng (bash cho số học viết nhiều dòng)
        while tok and tok.start() < m.start():
            if tok.lastgroup in ("dp", "dc"):
                dp = max(dp + (1 if tok.lastgroup == "dp" else -1), 0)
            elif tok.lastgroup == "bo" or bk and tok.lastgroup == "b":
                bk += -1 if tok[0] == "]" else 1
            last, tok = tok, next(toks, None)
        # Trong nháy, comment hay sau `\`: không phải heredoc, tìm tiếp sau phần đó
        if last and last.end() > m.start():
            m = HEREDOC_X.search(cmd, last.end())
            continue
        name = UNQUOTE_X.sub(lambda q: re.sub(r"\\([$`\"\\])|\\\n", r"\1", q[4]) if q[4] is not None
                             else ANSI_C_X.sub(ansi_c, q[2]) if q[2] is not None else q[1] or q[3] or "", m["word"])
        # Dịch bit, hay không chắc tên (từ dừng ở chỗ không phải dấu tách; tên nhiều dòng): không phải heredoc
        if dp or bk or "\n" in name \
                or cmd[m.end():m.end() + 1] not in ("", " ", "\t", "\n", ";", "&", "|", "(", ")", "<", ">"):
            m = HEREDOC_X.search(cmd, m.end())
            continue
        end = re.compile(r"([^\n]*)(?:\n(.*?))??(?:\n%s%s(?=\n|\Z)|\Z)" % (r"\t*" * bool(m["tab"]), re.escape(name)),
                         re.DOTALL).match(cmd, m.end())
        out += [cmd[pos:m.start()], place(cmd, m.start(), end[1], end[2], re.search(r"[\"']|\\(?!\n)", m["word"]))]
        pos = end.end()
        # Phần sau `<<` tới hết thân không đếm: thân là dữ liệu. Nháy lẻ trong thân che lố qua dòng đóng thì che lại từ
        # sau thân.
        while tok and tok.end() <= pos:
            tok = next(toks, None)
        if tok and tok.start() < pos:
            toks = ARITH_X.finditer(cmd, pos)
            tok = next(toks, None)
        m = HEREDOC_X.search(cmd, pos)
    return "".join(out) + cmd[pos:]


def here_strings(cmd):
    """Here-string `<<<` đưa vào shell (keep_shell_heredocs(bash=True)): bỏ khỏi dòng, đặt chuỗi như thân heredoc sau
    dòng đó (OPEN_RAW nếu trong nháy đơn hay `$'…'`, không thì OPEN: shell cha thay biến, `\\$` để shell con thay).
    `<<<` trong nháy, comment hay sau `\\` (ARITH_X) không phải toán tử. Lệnh đầu đoạn (sau `|;&` hay xuống dòng gần nhất)
    và cuối dòng dò dần theo vị trí: tuyến tính trên dòng dài có nhiều `<<<`."""
    out, pos, pend, eol = [], 0, [], 0
    toks, last = ARITH_X.finditer(cmd), None
    tok = next(toks, None)
    scan, fed_seg, line_end = 0, False, -1  # đã dò tới scan; đoạn hiện tại có tên shell chưa; cuối dòng đã tìm
    for m in HERESTR_X.finditer(cmd):
        while tok and tok.start() < m.start():
            last, tok = tok, next(toks, None)
        if last and last.end() > m.start():
            continue
        if pend and m.start() > eol:
            out += [cmd[pos:eol]] + pend
            pos, pend = eol, []
        chunk = cmd[scan:m.start()]
        cut = max(chunk.rfind(c) for c in "\n|;&")
        fed_seg = bool(SHELL_WORD_ANY.search(chunk[cut + 1:])) or (cut < 0 and fed_seg)
        scan = m.end()
        if line_end < m.end():
            line_end = cmd.find("\n", m.end())
            line_end = len(cmd) if line_end < 0 else line_end
        if not (fed_seg or HS_PIPE_SHELL.match(cmd, m.end(), line_end)):
            continue
        w = m[1]
        if w.startswith("$'"):
            body, raw = ANSI_C_X.sub(ansi_c, w[2:-1]), True
        elif w[0] == "'":
            body, raw = w[1:-1], True
        elif w[0] == '"':
            body, raw = re.sub(r'\\(["\n])', lambda x: "" if x[1] == "\n" else x[1], w[1:-1]), False
        else:
            body, raw = re.sub(r"\\([^$`\\])", r"\1", w), False
        out.append(cmd[pos:m.start()])
        pos, eol = m.end(), line_end
        pend.append("\n" + "\n".join(((OPEN_RAW if raw else OPEN), body, CLOSE)))
    if pend:
        out += [cmd[pos:eol]] + pend
        pos = eol
    return "".join(out) + cmd[pos:]


def snap_to_end(b):
    """SNAP_END trên chuỗi b của keep_shell_heredocs(snap=True). SNAP dời tới ngay trước xuống dòng thì chen thêm một khoảng
    trắng nếu ký tự trước nó không phải khoảng trắng: `-c\\s`, `eval\\s` khớp được như với xuống dòng."""
    def sub(m):
        last = m[1][-1:] or m.string[m.start() - 1:m.start()]
        return m[1] + (" " if m[2] is not None and last.strip() else "") + SNAP
    return SNAP_END.sub(sub, b)


def unwrap_shell_c(text, rx):
    """Thay `bash -c '<thân>'` (rx: SHELL_C_BODY hay SHELL_C_BODY_STRICT) bằng shell rồi thân giữa dòng OPEN_RAW và dòng
    CLOSE: thân là phạm vi shell con như thân <<'EOF'. Thân nháy kép được gỡ thoát như bash (`\\$`, `\\``, `\\"`, `\\\\` thành
    ký tự, `\\` + xuống dòng bỏ hẳn) mà vẫn dùng OPEN_RAW: biến cha không thoát mà cha tự thay cũng thành rỗng. Báo thừa, vì
    các cách đọc không gỡ vẫn thay giá trị của cha. Thân ANSI-C `$'…'` (chỉ SHELL_C_BODY_STRICT nhận) giải `\\n`, `\\t` thành
    xuống dòng, tab; escape khác giữ ký tự sau `\\` (`\\'` thành `'`): đủ để dò. Thân lồng nhau gỡ đệ quy bằng cùng rx."""
    def sub(m):
        body = m.group(2)[1:-1]
        if m.group(2)[0] == '"':
            body = re.sub(r'\\([$`"\\\n])', lambda x: "" if x[1] == "\n" else x[1], body)
        elif m.group(2)[0] == "$":
            body = re.sub(r"\\(.)", lambda x: {"n": "\n", "t": "\t"}.get(x[1], x[1]), body[1:])
        return "\n".join((m.group(1), OPEN_RAW, unwrap_shell_c(body, rx), CLOSE, ""))
    return rx.sub(sub, text)


def segments(cmd, tool="Bash", join=True, scoped=True, parent_env=False, comments=True, raw_marks=False,
             strict_assign=False, empty_body=True, blank=False, exact=False, pipe_scope=False, strict=False, pure=False,
             bash=False):
    """Các lệnh đơn trong một lệnh shell, dạng (để so mẫu, đầy đủ, thư mục cd gần nhất, có `$` trước khi thay biến).

    Bản để so mẫu thay chuỗi trong nháy bằng "" (trừ bash -c '...', cmd /c "...", eval), bản đầy đủ
    giữ nguyên để biết đích thật. Biến gán trong lệnh (S=/tmp/x; rm -rf $S) được thay theo thứ tự.
    join=False: không nối dòng tại `\\` + xuống dòng, tách như cũ.
    scoped=False: thân heredoc đưa vào shell không phải phạm vi riêng (như 6f32d5a): biến gán trong thân lọt ra ngoài,
    thân <<'EOF' thấy biến của shell cha; đoạn ngay sau một shell trơn, cách bằng xuống dòng, thừa hưởng thư mục.
    parent_env (chỉ có nghĩa khi scoped): thân <<EOF thấy biến của shell cha như tại toán tử heredoc (không thấy gán tạm
    trước lệnh hay lệnh sau toán tử trên dòng mở), biến gán trong thân không đổi phép thay tới hết thân (shell cha thay
    `$D` trong thân trước khi shell con chạy); thân <<'EOF' thấy biến của shell cha như đã export, kể cả gán tạm trước
    lệnh, biến gán trong thân vẫn áp.
    comments=False: che nháy như 6f32d5a, không biết comment (nháy trong `# don't` mở chuỗi).
    raw_marks (chỉ có nghĩa khi scoped): như 695e799, byte \\x01–\\x04 có sẵn trong lệnh đọc thành dấu, không có SNAP.
    strict_assign: chỉ đoạn toàn phép gán hay export/declare/typeset/local/readonly mới đổi biến; gán tạm trước lệnh khác
    (`D=x true`, `env D=x true`), NAME=VALUE là tham số của lệnh khác (`echo D=x`), và đoạn sau `&&`/`||`, trong ống hay
    chạy nền (`false && D=x`, `D=x | true`, `D=x &`) không đổi. Mặc định: NAME=VALUE ở đâu trong đoạn cũng đổi biến.
    empty_body=False: heredoc không nhận thân rỗng như 6f32d5a, cả khi scoped.
    blank (dùng với parent_env): thân <<EOF không nháy bắt đầu với env rỗng: không đoán biến mà shell cha dùng để thay. Giá
    trị đoán từng sai theo hướng làm lệnh xoá trông vô hại: `if false`, unset, declare -u, cd đổi PWD, `$[D=5]`, RANDOM, `_`,
    vòng lặp thay lại thân mỗi lần chạy, delimiter bash đọc khác audit (`<<EOF.x`, `<<EOF-1`, `EOF\r`), giá trị shell con
    brace-expand, nháy ở chế độ `| bash`.
    exact=True (dùng với scoped): đọc sát bash ở chỗ các cách trên đọc lệch theo hướng làm lệnh xoá trông vô hại. Thân
    `bash -c '…'` là phạm vi shell con (unwrap_shell_c): biến không export của cha rỗng trong thân, biến gán trong thân không
    ra ngoài. Các cách trên thế env của cha vào thân, để biến gán trong thân lọt ra, và che thân `-lc '…'` như một chuỗi.
    Nháy được che riêng trong từng vùng giữa các dấu, comment che như một chuỗi: nháy lẻ trong thân heredoc hay trong
    comment (`# don't`) không ghép với nháy của lệnh sau thành một chuỗi nuốt lệnh. Dòng mở heredoc là dòng logic:
    `bash \\⏎<<'EOF'` đưa thân vào bash (keep_shell_heredocs).
    pipe_scope (dùng với exact, PR #8): khâu của ống là shell con: phép gán và cd trong đoạn kề `|` không ra ngoài, còn
    phép gán sau `&&` vẫn áp (cách đọc chặt bỏ cả hai). Đoạn ngay sau `||` có thể không chạy: thư mục và biến nó vừa gán
    là không biết. Là một cách đọc thêm để hợp nhãn, không đổi cách đọc exact.
    strict=True (dùng với exact): đọc sát bash thêm ở chỗ exact giữ y như bản trước, để thêm cách đọc mà không đổi cách cũ.
    Thân -c gỡ bằng regex mở rộng (SHELL_C_BODY_STRICT: `bash +e -c '…'`, `bash -c -x '…'`, `bash -c - '…'`, `bash -c $'…'`);
    exact giữ regex của 1667825 vì sửa tại chỗ từng làm lệnh lồng mất nhãn. Bash: `\\'`, `\\"` ngoài nháy là ký tự thoát,
    không mở chuỗi nuốt lệnh sau (`echo it\\'s⏎rm -rf src 'x'`); `\\'` trong `$'…'` không đóng chuỗi. Thân heredoc có thể
    rỗng (`cat <<'EOF'⏎EOF⏎rm -rf src`). Thân <<EOF: shell cha thay `$D` bằng giá trị tại toán tử heredoc, trước gán tạm
    và lệnh sau toán tử trên dòng mở, trước khi shell con chạy (`D=/; bash <<EOF⏎D=/tmp/w; rm -rf $D` xoá /, `D=/; bash
    <<EOF; D=/tmp/w⏎rm -rf $D/x` xoá //x); `\\$D` để shell con thay bằng env của nó: env tại toán tử (coi như đã export)
    cộng gán tạm của lệnh nhận thân, rồi phép gán trong thân (`O=-f; bash <<EOF⏎O=-rf; rm \\$O /x` xoá /x). Đoạn nào trong
    thân mà thay như thế khác bản so mẫu cũ thì có thêm một đoạn phụ (bản so mẫu thay như bash, cùng bản đầy đủ): biến là
    cờ hay tên lệnh cũng khớp mẫu. Bản đầy đủ chỉ thay biến có cùng giá trị tại toán tử và lúc mở thân, để nguyên `\\$D`.
    Biến gán bằng read, mapfile, printf -v, for… (cả tên dính redirection hay trong nháy: `read D<<</etc`, `printf -v "D"`),
    trong một khâu của ống hay sau `||` là không biết; unset làm rỗng; eval, source, `.` làm mọi biến thành không biết.
    Here-string `<<<` không mở heredoc: dòng sau `cat <<< EOF` là lệnh.
    pure=True (dùng với strict): biến chỉ đổi theo phép gán thuần (PURE_STMT) chắc chạy ở shell này: đứng sau đầu lệnh, `;`
    hay xuống dòng (không sau `&&`, `||`, `|`, không sau `\\` lẻ), không trước `|`, không chạy nền, ngoài lệnh ghép, thân hàm
    và subshell. Đoạn khác làm mọi tên mà nó có thể gán thành không biết (bỏ khỏi env): `echo D=x`, gán tạm, `local`,
    `D[0]=`, `((D=0))`, `${D:=x}`, tên dính cờ (`read -aD`), lệnh viết có nháy hay `\\` (`r\\ead D`). Gán IFS (giá trị
    tách thành đích khác) hay gọi hàm đã định nghĩa (thân hàm gán gì cũng được) làm mọi biến thành không biết, và sau IFS
    không học biến nào nữa. Là một cách đọc thêm để hợp nhãn, không đổi cách đọc strict.
    bash=True (dùng với strict): nhận heredoc và here-string như bash (keep_shell_heredocs(bash=True), port vibrant-pascal
    970114a) thay cho HEREDOC_STRICT. Là một cách đọc thêm để hợp nhãn.
    """
    join = join and tool != "PowerShell"
    body = keep_shell_heredocs(cmd, join, scoped, raw_marks, empty_body, exact, parent_env or strict, strict, bash)
    if strict and scoped and not raw_marks:
        body = snap_to_end(body)
    if join:  # nối dòng như bash trước khi tách: bỏ `\` + xuống dòng, trừ khi `\` đó bị thoát (`\\`)
        body = LINE_JOIN.sub(r"\1", body)
    if exact:  # sau nối dòng: `\` + xuống dòng trong thân nháy đơn là chữ với shell cha nhưng shell con nối dòng
        body = unwrap_shell_c(body, SHELL_C_BODY_STRICT if strict else SHELL_C_BODY)
    store = []

    def keep(m):
        if m[0].startswith("\\"):  # ký tự thoát ngoài nháy (QUOTED_XB): giữ nguyên, không phải chuỗi
            return m[0]
        if m[0].startswith("#") and not exact:
            return m[0]  # comment giữ nguyên văn như trước, chỉ không để nháy trong nó mở chuỗi (exact cất như chuỗi)
        store.append(m.group(0))
        return "\0%d\0" % (len(store) - 1)

    def unkeep(m):
        # Lệnh có sẵn chuỗi dạng chỗ giữ (byte NUL, số, NUL) mà số không có trong store thì giữ nguyên, không ném lỗi.
        # Bỏ số 0 đầu và so độ dài trước: int() ném lỗi với chuỗi quá 4300 chữ số.
        n = m[1].lstrip("0") or "0"
        return store[int(n)] if len(n) < 10 and int(n) < len(store) else m[0]

    shell_c = bool(SHELL_C.search(body))
    ps = tool == "PowerShell"
    quoted = (QUOTED_PS if ps else QUOTED) if comments else (QUOTED_PS_6F32D5A if ps else QUOTED_6F32D5A)
    if exact:  # PowerShell không thoát bằng `\`: strict che nháy như exact
        quoted = QUOTED_PS_X if ps else QUOTED_XB if strict else QUOTED_X
    # exact: che riêng từng vùng giữa các dấu để nháy không ghép qua ranh giới thân (`echo don't` trong thân với `'x'` sau EOF)
    regions = re.split("([" + OPEN + OPEN_RAW + CLOSE + NOT_LAST + "])", body) if exact else [body]
    marked = body if shell_c else "".join(p if i % 2 else quoted.sub(keep, p) for i, p in enumerate(regions))
    out, ctx, env, sep, saved, inherit, frozen, snap = [], "", {}, None, [], False, False, None
    # Comment chạy tới xuống dòng kế: `;`, `&&`, `|` trong nó không ngắt lệnh, cd trong nó không chạy. comment: phần đang
    # xét nằm trong comment mở ở phần trước; csep: dấu ngắt thật ngay trước comment mở đầu phần (`true || # x`).
    comment, csep = False, None
    # strict_assign: phép gán trong subshell `( … )`, trong nhóm hay danh sách chạy nền (`{ …; } &`, `D=x && a &`) chạy ở
    # shell con. groups: ngăn xếp (dấu mở, env lúc mở) của nhóm đang mở; lst: env lúc mở danh sách ở ngoài mọi nhóm;
    # bg: phần trước có `&` chạy nền (lệnh sau nó mở danh sách mới).
    groups, lst, bg = [], {}, False
    # strict: ngăn xếp song song với saved: env mà shell cha đã thay vào thân <<EOF đang mở (None: thân không bị thay), gồm
    # env lúc mở thân, env tại toán tử chỉ giữ biến có cùng giá trị lúc mở thân, env tại toán tử, và env của shell con (kid:
    # env tại toán tử cộng gán tạm của lệnh nhận thân, rồi theo phép gán trong thân).
    pinned = []
    # pure: số lệnh ghép và thân hàm đang mở (kw), số `(` đang mở (par), tên hàm đã định nghĩa, IFS đã bị gán
    # case: số case đang mở (`)` của mẫu không đóng subshell); anded: comment vừa đóng mở ngay sau `&&` (`false && # c⏎D=x`:
    # D=x vẫn là vế phải của `&&`)
    kw = par = case = 0
    funcs, ifs_dirty, anded = set(), False, False
    parts = re.split("(" + SPLIT.pattern + ")", marked)
    for i, seg in enumerate(parts):
        if i % 2:  # dấu tách: lấy dấu đầu tiên không phải xuống dòng (bash cho xuống dòng ngay sau &&, ||, |)
            if sep in (None, "\n"):
                sep = seg
            if comment and seg == "\n":
                # Hết comment. Comment ngay sau `||`/`|` không ngắt chuỗi: lệnh dòng sau vẫn là vế phải của `||` hay của ống
                comment = False
                anded = csep == "&&"
                if csep in ("||", "|"):
                    sep = csep
            continue
        seg = seg.strip()
        if not seg:
            continue
        raw = re.sub(r"\0(\d+)\0", unkeep, seg)
        # `#` đầu từ mở comment: ở đầu phần (kể cả comment exact cất trong kho) hay giữa phần (bản che nháy; chế độ shell_c
        # không che nên `#` trong nháy cũng tính: chỉ làm mất thư mục cd, không bớt nghi ngờ).
        commented = comment
        if not comment and (raw.lstrip("({ ").startswith("#") or re.search(r"(?:^|[\s()])#", seg)):
            comment, csep = True, sep if raw.lstrip("({ ").startswith("#") else None
        # Đoạn có toán tử heredoc đưa vào shell: bỏ SNAP rồi đọc như cũ, ghi env trước và sau phép gán của đoạn, và env của
        # shell con: env trước đoạn cộng phép gán ở phần trước SNAP (gán tạm của lệnh nhận thân, có cả khi lệnh ở trong ống).
        snapped = scoped and not raw_marks and SNAP in raw
        if snapped:
            op = raw[:raw.index(SNAP)]
            seg, raw, pre = seg.replace(SNAP, "").strip(), raw.replace(SNAP, "").strip(), dict(env)
            if not seg:
                snap = pre, pre, pre
                continue
        mark_only = scoped and not raw.strip(OPEN + OPEN_RAW + CLOSE + NOT_LAST)
        # pipe_scope (PR #8): một khâu của ống chạy ở shell con, phép gán và cd trong đoạn ngay trước hay ngay sau `|`
        # không tới khâu sau hay lệnh sau ống, còn phép gán sau `&&` vẫn áp: `true && D=/srv/⏎x | D=/tmp/w/⏎rm -rf ${D}src`
        # xoá /srv/src (cách đọc chặt bỏ cả D=/srv/, cách đọc lỏng nhận D=/tmp/w/). Đoạn ngay sau `||` chỉ chạy khi lệnh
        # trước lỗi: thư mục thành không biết, biến nó gán thành chưa biết.
        piped = pipe_scope and not mark_only and (sep == "|" or parts[i + 1:i + 2] == ["|"])
        maybe = pipe_scope and not mark_only and sep == "||"
        # Chỉ `&&` giữ thư mục: sau `;`, `||`, xuống dòng lệnh vẫn chạy khi cd lỗi, `|` chạy ở shell con. Riêng đoạn đầu
        # của thân heredoc đưa vào shell (sau OPEN; không dấu thì sau shell trơn) chạy trong shell đó, ở thư mục của nó.
        if not mark_only:
            inherit = inherit or not scoped and sep == "\n" and bool(out and LOCAL_SHELL.match(out[-1][0]))
            if sep != "&&" and not inherit:
                ctx = ""
            inherit = False
        # Gán sau `&&`, `||` có thể không chạy; trong ống (`|` trước hay sau) hay chạy nền (`&`) thì chạy ở shell con.
        background = re.search(r"[^<>|&]&(?![>&])", seg)
        detached = sep in ("&&", "||", "|") or parts[i + 1:i + 2] == ["|"] or background
        opens = re.match(r"[({\s]*", seg).group().replace(" ", "").replace("\t", "") if strict_assign else ""
        closes = re.findall(r"(?:^|[\s;])\}(?=[\s;&|)]|$)|\)", seg) if strict_assign else []
        closes = closes[seg.count("$(") + seg.count("$(("):]  # bỏ `)` đóng `$(…)`, `$((…))`
        if strict_assign and not groups and (sep in (None, ";", "\n") or bg) and not mark_only:
            lst = dict(env)  # mở danh sách mới ở ngoài mọi nhóm
        if strict_assign and background and not groups and not opens and not closes:
            env = dict(lst)  # `D=x && a & rm $D`: cả danh sách trước `&` chạy nền, lệnh sau `&` thấy env lúc mở danh sách
        groups += [(o, dict(env)) for o in opens]
        bg = bool(background)
        lone = sep in (None, ";", "\n") and not anded  # pure: dấu ngắt thật trước đoạn là đầu lệnh, `;` hay xuống dòng
        if not raw.lstrip("({ ").startswith("#"):
            anded = False
        after_or_pipe, sep = sep in ("||", "|"), None
        # strict: trong thân <<EOF, biến đã được shell cha thay (pinned), không theo phép gán trong thân. Bản so mẫu thay bằng
        # env lúc mở thân như bản trước (mẫu khớp như cũ); bản đầy đủ (benign_delete đọc) chỉ thay biến có cùng giá trị tại
        # toán tử và lúc mở thân, nên không tin giá trị nào mà bản trước không tin. Bản so mẫu thứ hai (plain2) thay như bash
        # (expand_body): `$X` bằng env tại toán tử, `\$X` bằng env của shell con; khác bản so mẫu thì thành một đoạn phụ cùng
        # bản đầy đủ, nên mẫu so trên cả hai mà đoạn cũ giữ nguyên. Biến là cờ hay tên lệnh (`rm $O /x`, `\$C -rf /x`) chỉ
        # khớp mẫu khi thay đúng giá trị.
        pin = pinned[-1] if pinned else None
        shown, values = pin[:2] if pin else (env, env)
        if frozen or pin:  # thân <<EOF: `\$` là `$` chữ, shell cha không thay; shell con thay bằng env không biết.
            # Chỉ thay biến ở các mảnh giữa những `\$` lẻ: không cần chỗ giữ nên không phụ thuộc ký tự có trong lệnh
            full = "".join(x if k % 2 else expand(x, values) for k, x in enumerate(re.split(r"((?<!\\)(?:\\\\)*\\\$)", raw)))
        else:
            full = expand(raw, values)
        plain = expand(re.sub(r"\0\d+\0", '""', seg), shown)
        plain2 = expand_body(re.sub(r"\0\d+\0", '""', seg), pin[2], pin[3]) if pin else plain
        kid = pin[3] if pin else {}  # phép gán áp cả cho env của shell con; ngoài thân <<EOF thì vào một dict bỏ đi
        if shell_c:
            plain, plain2 = re.sub(r"[\"']", " ", plain), re.sub(r"[\"']", " ", plain2)
        assigns = not strict_assign or not detached and ASSIGN_STMT.match(re.sub(r"(?:^|\s)#.*", "", seg.lstrip("({ ")))
        before = (dict(env), ctx) if piped else None
        # strict: phép gán trong một khâu của ống chạy ở shell con (khâu cuối có thể không, lastpipe), sau `||` có thể không
        # chạy: không biết giá trị
        forget = strict and (after_or_pipe or parts[i + 1:i + 2] == ["|"])
        sure = True
        if pure and not mark_only:
            # Đoạn đã che nháy, bỏ comment cuối (exact cất comment như chuỗi); mã của đoạn bỏ comment, nháy và `\`
            stmt = re.sub(r"\s*\0(\d+)\0\s*$", lambda m: "" if unkeep(m).startswith("#") else m[0], seg)
            code = re.sub(r"[\"'\\]", "", re.sub(r"\0(\d+)\0", lambda m: "" if unkeep(m).startswith("#") else unkeep(m), seg))
            cont = i >= 2 and bool(re.search(r"(?<!\\)(?:\\\\)*\\$", parts[i - 2]))  # `echo a\; D=x`: `;` là chữ
            sure = (lone and not commented and not cont and not ifs_dirty and kw == 0 and par == 0
                    and parts[i + 1:i + 2] != ["|"] and not re.search(r"[(){}&]", stmt) and bool(PURE_STMT.match(stmt)))
            if "(" in stmt or "function" in stmt:
                for f1, f2 in FUNC_DEF.findall(stmt):
                    funcs.add(f1 or f2)
            words = [w for w in re.split(r"[\s();&|<>`]+", code) if w]
            # Hàm trùng tên lệnh của phép gán thuần (`export() {`), hay lệnh đầu đoạn qua biến khi đã có hàm (`$F`): có thể
            # là lời gọi hàm
            sure = sure and not (funcs & set(words[:1])) and not (funcs and words[:1] and re.search(r"[$`]", words[0]))
            if not commented:
                opened = COMPOUND_OPEN.findall(stmt)
                kw += len(opened)
                case += opened.count("case")
                if COMPOUND_CLOSE.match(stmt) and not cont:  # `echo a\; fi`: `fi` là chữ, không đóng lệnh ghép
                    kw = max(kw - 1, 0)
                    case = max(case - stmt.startswith("esac"), 0)
                # Trong case, `)` có thể là của mẫu (`a)`): không trừ, chỉ làm biến thành không biết lâu hơn
                par = max(par + stmt.count("(") - (0 if case else stmt.count(")")), 0)
            toks = [t for t in re.split(r"[\s(){};&|<>!`]+", code) if t]
            if re.search(r"(?<![\w$])(?<!\$\{)IFS(?!\w)", code):
                ifs_dirty = True
            called = funcs & (set(toks) | set(words)) or (funcs and words[:1] and re.search(r"[$`]", words[0]))
            if ifs_dirty or (not sure and called):
                for x in [env, kid] + (saved if ifs_dirty else []) + [y for p in pinned if p for y in p]:
                    x.clear()  # sau IFS cả env đã chụp (thân heredoc, phạm vi lồng) cũng thành không biết
            elif not sure:
                drop = set(re.findall(r"\$\{#?([A-Za-z_]\w*):?=", code))
                flags = list(itertools.takewhile(lambda t: t.startswith("-"), toks[1:]))
                if not (toks[:1] == ["unset"] and any("f" in t for t in flags)):  # `unset -f D` chỉ bỏ hàm
                    named = bool(set(toks) & NAME_FLAGS)
                    for t in toks:
                        m = IDENT.match(t)
                        if m and (m.end() == len(t) or t[m.end()] in "=+["):
                            drop.add(m[0])
                        elif named and re.fullmatch(r"-[A-Za-z]+", t):
                            drop.update(t[k:] for k in range(1, len(t)))
                for name in drop:
                    env.pop(name, None)
                    kid.pop(name, None)
        for name, val in ((ASSIGN_EMPTY if pure else ASSIGN).findall(full) if assigns and not frozen and sure else ()):
            if forget:
                env.pop(name, None)
                kid.pop(name, None)
            else:
                env[name] = kid[name] = val.strip("\"'")
        if snapped:
            snap = pre, dict(env), {**pre, **{n: v.strip("\"'") for n, v in ASSIGN.findall(expand(op, values))}}
        if before:  # khâu của ống: phép gán trong đoạn không ra ngoài. Trả env trước khi `)` đóng nhóm lấy env lúc mở nhóm
            env = before[0]
        for _c in closes:  # subshell đóng, hay nhóm chạy nền: phép gán bên trong không ra ngoài
            o, at = groups.pop() if groups else ("(", dict(lst))
            if o == "(" or background:
                env = at
        if strict_assign and background and not groups and (opens or closes):
            env = dict(lst)
        head, lead = full.lstrip("({ "), plain.lstrip("({ ")
        if strict:
            # Tên lấy từ bản đầy đủ đã bỏ ký tự nháy, tách cả ở redirection: `read D<<</etc`, `printf -v "D"`, `unset 'D'`.
            # Cờ -f của unset chỉ tìm ngoài nháy và comment như trước: `unset D # -f` vẫn làm D rỗng.
            words = set(re.split(r"[\s(){}!<>;&|]+", re.sub(r"[\"']", "", full)))
            if EVAL.search(lead):
                env.clear()
                kid.clear()
            elif words & SETS_NAMES or (words & {"printf", "wait"} and any(w[:2] in ("-v", "-p") for w in words)):
                for word in words | {w[2:] for w in words if w[:2] in ("-v", "-p")}:  # `printf -vD`: tên dính cờ
                    env.pop(word, None)
                    kid.pop(word, None)
            elif "unset" in words and not any(w[:1] == "-" and "f" in w for w in re.split(r"[\s(){}!]+", plain)):
                env.update(dict.fromkeys(filter(IDENT.fullmatch, words), ""))
                kid.update(dict.fromkeys(filter(IDENT.fullmatch, words), ""))
        m = CD.match(head)
        if m and m.group(2).strip().strip("\"'") not in ("-", ""):
            target = m.group(2).strip().strip("\"'")
            # Chỉ tin đích một token, không mở bằng `-` (kể cả "-L") hay `+` (pushd +1 xoay ngăn xếp), không còn `$` hay backtick
            # sau khi thay biến đã biết, không có `..` (kể cả .'.', .\.), cd không ngay sau `||` (`(a || cd x) && rm` bỏ qua
            # cd khi a thành công) hay `|` (cd chạy ở shell con của ống): còn lại không biết thư mục
            if CD_WORD.match(lead) and not after_or_pipe and not commented and not target.startswith(("-", "+")) \
                    and not re.search(r"[$`]", target) and ".." not in re.sub(r"[\"'\\]", "", target):
                ctx = target if is_absolute(target) else (ctx + "/" + target)
            else:
                ctx = ""
        elif m or full[:1] in "({" or re.match(r"^(cd|popd|pop-location|pushd|set-location|sl)\s*(-\s*)?$", head, re.IGNORECASE):
            ctx = ""  # cd không tham số, cd - (kể cả "-"), popd, subshell: không còn biết thư mục
        if CHDIR.search(lead[len(m.group(1)):] if m else lead):
            ctx = ""  # đổi thư mục không ở dạng cd đơn đầu đoạn: không biết thư mục
        # Từ có nháy hay `\` (tách theo khoảng trắng ngoài nháy: `c"d"` là một từ) mà bỏ nháy và `\` đi thì thành tên lệnh
        # đổi thư mục (`"cd"`, `'cd'`, `c\d`, `$'cd'`, `"."` đầu đoạn): bash vẫn chạy lệnh đó, CHDIR (bản che nháy) không thấy.
        # Từ có `$'…'` chứa `\` (escape ANSI-C: `$'\x63d'` là cd) thì không biết tên lệnh.
        for k, word in enumerate(seg.lstrip("({ ").split()):
            word = re.sub(r"\0(\d+)\0", unkeep, word)
            name = re.sub(r"\$?[\"']|\\", "", word)
            if name != word and (re.fullmatch(CHDIR_NAMES, name, re.IGNORECASE) or (name == "." and k == 0)
                                 or re.search(r"\$'[^']*\\", word)):
                ctx = ""
        if BACKGROUND.search(seg):
            ctx = ""  # `cd x && a & b`: cả `cd x && a` chạy nền ở shell con, b chạy ở thư mục cũ
        if plain2 != plain and CHDIR.search(plain2.lstrip("({ ")):
            ctx = ""  # thân <<EOF: tên lệnh qua biến là cd (`$C /`, `\$C /`): không biết thư mục
        if not mark_only:
            if plain2 != plain:  # đoạn phụ đứng trước: out[-1] (LOCAL_SHELL đọc ở dấu mở thân) vẫn là đoạn như cũ
                out.append((plain2, full, ctx, "$" in raw))
            out.append((plain, full, ctx, "$" in raw))
        if before:
            ctx = before[1]
        elif maybe:
            ctx = ""
            # Biến mà đoạn nêu thành chưa biết, kể cả ở cách đọc chặt (đoạn sau `||` không gán gì): thêm nghi ngờ thay vì
            # giữ giá trị cũ; cách đọc exact không pipe_scope vẫn trong phép hợp nên không mất nhãn nhờ giá trị cũ.
            for name, _val in ASSIGN.findall(full):
                env.pop(name, None)
        if re.search(r"[)}]", seg):
            ctx = ""  # subshell, nhóm hay $( ) vừa đóng: thư mục cd bên trong không còn áp dụng
        # Dò dấu trên raw: nháy lẻ trong thân (`# don't`) ghép với nháy sau EOF có thể nuốt dòng dấu vào một chuỗi.
        # scoped=False không đặt dấu: byte \x01–\x04 có sẵn trong lệnh là ký tự thường như ở 6f32d5a.
        for mark in (re.findall("[" + OPEN + OPEN_RAW + CLOSE + NOT_LAST + "]", raw) if scoped else ()):
            if mark == CLOSE:  # biến chỉ gán trong thân là rỗng ở shell cha, biến có từ trước lấy lại giá trị đã chụp
                ctx, env, inherit, frozen = "", {**dict.fromkeys(env, ""), **(saved.pop() if saved else {})}, False, False
                if pinned:
                    pinned.pop()
            elif mark == NOT_LAST:
                inherit = False
            else:  # thân chạy ở shell con: thừa hưởng thư mục nếu là shell cục bộ, biến gán trong thân không ra ngoài.
                # <<'EOF' không được shell cha thay biến: biến của shell cha là rỗng trong thân, trừ biến đã export (cách
                # đọc scoped=False và parent_env thấy chúng). parent_env: shell cha thay biến trong thân <<EOF trước, gán
                # trong thân không đổi phép thay. Env của thân chụp ở toán tử heredoc (SNAP), trước lệnh sau toán tử trên
                # dòng mở: <<EOF không thấy gán tạm trước lệnh (shell cha thay), <<'EOF' thấy (shell con nhận gán tạm).
                # exact: phạm vi lồng nhau (bash -c trong bash -c hay trong thân heredoc) chụp env thành ngăn xếp; cách
                # đọc cũ chỉ nhớ phạm vi mở sau cùng như 2f68e61
                saved = (saved if exact else []) + [env]
                if strict:
                    # Phạm vi lồng trong thân <<EOF vẫn theo giá trị của shell cha ngoài cùng, với bản chép env của shell con
                    # (phép gán trong phạm vi lồng không ra ngoài). Thân <<EOF: shell cha thay bằng env tại toán tử (SNAP),
                    # trước gán tạm và lệnh sau toán tử trên dòng mở; biến có giá trị khác lúc mở thân (giá trị bản trước
                    # dùng) thì bản đầy đủ không thay. Shell con bắt đầu với env tại toán tử cộng gán tạm của lệnh nhận thân
                    # (snap[2]; lệnh sau toán tử chưa chạy), coi như mọi biến đã export. SNAP có thể đứng trước thân -c gỡ ra
                    # sau toán tử: dấu mở của thân -c không bỏ nó.
                    at, top = snap[0] if snap else env, pinned[-1] if pinned else None
                    pinned.append(top[:3] + (dict(top[3]),) if top else
                                  (dict(env), {k: v for k, v in at.items() if env.get(k) == v}, dict(at),
                                   dict(snap[2] if snap else env)) if mark == OPEN else None)
                env = dict.fromkeys(env, "") if mark == OPEN_RAW and not parent_env else dict(env)
                if parent_env and snap:
                    env = dict(snap[1] if mark == OPEN_RAW else snap[0])
                if mark == OPEN or not strict:
                    snap = None
                if blank and mark == OPEN:
                    env = {}
                frozen = parent_env and mark == OPEN
                inherit = bool(out and LOCAL_SHELL.match(out[-1][0]))
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


def benign_delete(full, ctx, worktree=True, tool="Bash"):
    """worktree=False: không nhận đích trong worktree agent (đích thật có thể khác đích ghi)."""
    # Biến hay lệnh lồng chưa thay được có thể chứa `..`, đường tuyệt đối hay khoảng trắng (tách thành đích khác, kể cả từ
    # token trông như cờ: `-$X`), dù đứng sau thư mục tạm hay tên lành.
    if re.search(r"[$`]", full):
        return False
    toks = [t.strip("\"'") for t in TOKEN.findall(full)]
    if any(re.split(r"[\\/]", t)[-1].lower() == "xargs" for t in toks):
        return False  # đích đọc từ stdin: không biết
    wsl = False
    while toks and toks[0].lower() in ("sudo", "doas", "wsl", "command", "builtin"):
        wsl = wsl or toks[0].lower() == "wsl"
        toks = toks[1:]
    cmd_style = bool(toks) and toks[0].lower() in ("rd", "del", "erase", "rmdir")  # /s /q là cờ của cmd
    args = toks[1:]
    if not [t for t in args if t and not t.startswith("-") and not (cmd_style and CMD_FLAG.match(t))]:
        return False  # như trước: ngoài cờ không thấy đích nào thì không biết lệnh xoá gì
    end = args.index("--") if "--" in args else len(args)  # sau `--` đầu tiên mọi token là đích, kể cả token mở bằng `-`
    targets = [t for t in args[:end] if t and not t.startswith("-") and not (cmd_style and CMD_FLAG.match(t))]
    targets += [t for t in args[end + 1:] if t]
    # rm của BSD/macOS (getopt POSIX, không hoán vị) thôi nhận cờ ở toán hạng đầu tiên: mọi token sau đó là đích, kể cả
    # `-x` và `--`. Lấy hợp với cách đọc GNU ở trên. Không áp cho cmd và PowerShell (`rm x -Recurse` là Remove-Item), trừ qua wsl.
    if not cmd_style and (tool != "PowerShell" or wsl):
        i = 0
        while i < len(args) and args[i].startswith("-") and args[i] not in ("-", "--"):
            i += 1
        if args[i:i + 1] != ["--"]:  # `--` trước toán hạng đầu: đích là các token sau nó, như cách đọc GNU
            targets += [t for t in args[i:] if t]
    worktree = worktree and not any(PS_NAMED.match(t) for t in toks)
    for t in targets:
        u = re.sub(r"\\(.)|[\"']", r"\1", t)  # bỏ nháy và `\` như bash: `.'.'`, `.\.` là `..`
        if ".." in re.split(r"[\\/]+", t) or ".." in re.split(r"[\\/]+", u):
            return False
        if worktree and agent_worktree(t):
            continue
        if t.endswith("/"):
            return False  # rm đi theo symlink ở thành phần cuối: xoá nội dung thư mục mà link trỏ tới, tên nào cũng vậy
        if benign_path(t):
            continue
        # Chỉ tin thư mục cd khi đích chắc là tương đối và ở trong thư mục đó. Brace, extglob (`{a,/}`, `+(.)`; biến, lệnh lồng
        # đã loại ở đầu hàm): bash thay trước khi rm chạy, có thể thành đường tuyệt đối hay có `..`. Glob khớp được `..` ở
        # bash < 5.2 (chưa có globskipdots): `?`, `[` ở bất kỳ đâu, hay thành phần mở bằng `.` có `*` (`.?/.?/home`,
        # `.[.]/src`, `.*/src`); `*.o` vẫn tin được.
        rel = not is_absolute(t) and not is_absolute(u) and not re.search(r"[$`{(?\[]", t) \
            and not any(x.startswith(".") and "*" in x for x in re.split(r"[\\/]+", u))
        if rel and ctx and benign_path(ctx):
            continue
        return False
    return True


def reading_key(cmd, tool, combo, bodies):
    """Lớp của một tổ hợp tham số segments (combo: join, scoped, parent_env, comments, raw_marks, strict_assign,
    empty_body, blank, exact, pipe_scope, strict, pure, bash): hai tổ hợp cùng lớp cho cùng danh sách đoạn. bodies: bộ đệm chuỗi b của
    một lệnh.

    Vòng tách đoạn của segments chỉ đọc chuỗi b (lệnh sau keep_shell_heredocs, nối dòng, gỡ thân -c: tính y như các bước
    đầu của segments, sửa ở đó thì sửa cả ở đây) và các tham số dưới đây; join, empty_body chỉ tác động qua b. Lớp bỏ qua
    tham số khi b cho thấy nó không đổi được đoạn nào:
    - strict_assign, blank, parent_env (ngoài SNAP đã ở b) chỉ đổi env, mà env chỉ vào đoạn qua expand, chỉ thay sau `$`.
      parent_env, blank cũng chỉ tác động ở dấu mở thân.
    - exact (ngoài b) che comment như chuỗi, che nháy theo vùng giữa các byte dấu \\x01–\\x04, chồng env ở dấu mở. Không
      `#` và byte dấu thì che như comments=False. comments: hai cách che nháy chỉ khác ở `#`.
    - raw_marks (ngoài b) chỉ quyết đoạn có SNAP có được bỏ SNAP không.
    - scoped (ngoài b) đọc byte dấu, và scoped=False cho đoạn ngay sau shell trơn (LOCAL_SHELL) thừa hưởng thư mục: đoạn
      chỉ trông như `bash`, `sh -s`… khi b có "sh" hay có `$` để ghép ra. SNAP ở b khi scoped, không raw_marks thì đi
      cùng dấu mở thân.
    - pipe_scope (PR #8) đổi cả thư mục lẫn env quanh `|` và `||` ngoài b: giữ nguyên trong lớp, không gộp.
    - strict đổi b (HEREDOC_STRICT, SHELL_C_BODY_STRICT, SNAP ở cuối lệnh có toán tử) và, ngoài b, cách che nháy
      (QUOTED_XB) cùng env (read, unset, eval…, gán trong ống, thân <<EOF): giữ nguyên trong khoá đệm b và trong lớp,
      không gộp.
    - pure chỉ đổi env (ngoài b), nhưng theo đếm lệnh ghép, tên hàm, IFS trên cả lệnh: giữ nguyên trong lớp, không gộp.
    - bash đổi b (heredoc, here-string như bash): giữ nguyên trong khoá đệm b và trong lớp, không gộp."""
    join, scoped, parent_env, comments, raw_marks, strict_assign, empty_body, blank, exact, pipe_scope, strict, pure, bash = combo
    join = join and tool != "PowerShell"
    k = (join, scoped, parent_env, raw_marks, empty_body, exact, strict, bash)
    if k not in bodies:
        b = keep_shell_heredocs(cmd, join, scoped, raw_marks, empty_body, exact, parent_env or strict, strict, bash)
        if strict and scoped and not raw_marks:
            b = snap_to_end(b)
        if join:
            b = LINE_JOIN.sub(r"\1", b)
        bodies[k] = unwrap_shell_c(b, SHELL_C_BODY_STRICT if strict else SHELL_C_BODY) if exact else b
    b = bodies[k]
    dollar, marked = "$" in b, bool(re.search("[" + OPEN + OPEN_RAW + CLOSE + NOT_LAST + "]", b))
    exact = exact and ("#" in b or marked)
    scoped = scoped or not (marked or dollar or "sh" in b)
    return (b, scoped, exact, "#" in b and not exact and comments, scoped and SNAP in b and raw_marks,
            dollar and strict_assign, dollar and (OPEN in b or OPEN_RAW in b) and parent_env, dollar and OPEN in b and blank,
            pipe_scope, strict, pure, bash)


def reading_combos(cmd, tool="Bash"):
    """Mọi tổ hợp tham số segments (join, scoped, parent_env, comments, raw_marks, strict_assign, empty_body, blank,
    exact, pipe_scope, strict, pure, bash) mà suspicious_labels đọc rồi hợp nhãn, cách gần bản cũ trước."""
    # Đọc `\` cuối dòng theo cả hai cách như guard (hỏi thừa chứ không bỏ sót): nối dòng có thể dán dòng sau vào cd hay
    # thân heredoc làm lệnh xoá trông vô hại, nên chỉ được thêm nghi ngờ. Luôn xét cả hai: `\` cuối heredoc chưa đóng cũng bị nối.
    # Thân heredoc đưa vào shell cũng đọc ba cách: như 6f32d5a, phạm vi riêng (scoped), và phạm vi riêng mà thân <<EOF
    # thấy biến của shell cha như lúc mở (parent_env: shell cha thay `$D` trước, gán trong thân không đổi phép thay;
    # `\$D` thì shell con thay, chỉ cách scoped đọc đúng), thân <<'EOF' thấy biến của shell cha như đã export (cách
    # scoped=False cũng vậy nhưng không kéo dòng nên không thấy thân chỉ được đưa vào shell nhờ `\` cuối dòng mở).
    # Che nháy đọc hai cách: như 6f32d5a (comments=False) và biết comment (`# don't` không mở chuỗi nuốt dòng sau).
    # Lệnh có sẵn byte \x01–\x05: cách đọc scoped đọc thêm như 695e799 (raw_marks: byte thành dấu, không SNAP). Bash coi
    # byte là chữ, nhưng dấu giả xoá env bù được lỗi khác làm lệnh xoá trông vô hại (gán tạm, heredoc lồng).
    # Lệnh có NAME=: mọi cách trên đọc thêm phép gán chặt (strict_assign: `D=x true`, `echo D=x`, `false && D=x`,
    # `D=x | true`, `D=x &` không đổi biến). Dò NAME= cả ngay sau `;&|` hay nháy: `true;D=x true` chỉ có `^D=x` cho
    # ASSIGN sau khi segments tách đoạn.
    # Lệnh có heredoc thân rỗng: mọi cách đọc scoped đọc thêm heredoc như 6f32d5a (empty_body=False, thân tới dấu đóng sau).
    # Mỗi cách có thể đọc sai export, thân rỗng, `\` cuối dòng mở, `\$` hay nháy theo hướng làm lệnh xoá trông vô hại,
    # nên chỉ lấy hợp. Cách gần bản cũ xét trước. PowerShell không nối dòng tại `\`.
    # Cách đọc exact (thân bash -c là phạm vi shell con, nháy che theo vùng giữa các dấu, comment che như chuỗi, dòng mở
    # heredoc là dòng logic) xét sau cùng, cũng chỉ lấy hợp: nó cho biến cha là rỗng cả khi đã export hay được cha thay
    # trong nháy kép, và che chữ trong comment (bản nối dòng còn dán dòng sau vào comment), nên có chỗ nghi ít hơn cách cũ.
    # Exact cũng đọc thêm như các cách đọc scoped: raw_marks (lệnh có byte dấu: như PR #5 trước khi byte được trung hoà),
    # strict_assign (lệnh có NAME=), empty_body=False (lệnh có heredoc thân rỗng: như PR #5 trước khi nhận thân rỗng).
    # Cách đọc strict (exact cộng các chỗ đọc sát bash hơn mà exact phải giữ như bản trước) xét sau cùng, chỉ lấy hợp:
    # sửa một cách đọc tại chỗ từng làm mất nhãn ở lệnh mà cách cũ đọc đúng, thêm cách đọc thì không. Nó đọc thêm raw_marks
    # như exact: trước khi byte dấu được trung hoà, nó đọc byte có sẵn thành dấu.
    joins = (True,) if tool == "PowerShell" else (False, True)
    marks = (False, True) if re.search("[" + OPEN + OPEN_RAW + CLOSE + NOT_LAST + SNAP + "]", cmd) else (False,)
    stricts = (False, True) if re.search(r"(?:^|[\s;&|'\"])[A-Za-z_][A-Za-z0-9_]*=", cmd) else (False,)
    empties = (True, False) if any(m["body"] is None for m in HEREDOC.finditer(cmd)) else (True,)
    combos = [(join, scoped, parent_env, comments, raw_marks, strict_assign, empty_body, False, False, False, False, False,
               False)
              for strict_assign in stricts for comments in (False, True)
              for scoped, parent_env in ((False, False), (True, False), (True, True))
              for raw_marks in (marks if scoped else (False,)) for empty_body in (empties if scoped else (True,))
              for join in joins]
    if re.search(r"<<-?\s*[A-Za-z_]", cmd):  # có heredoc không nháy: thân không đoán biến của shell cha (blank)
        combos += [(join, True, True, True, False, False, True, True, False, False, False, False, False) for join in joins]
    combos += [(join, True, False, True, raw_marks, strict_assign, empty_body, False, True, False, False, False, False)
               for strict_assign in stricts for raw_marks in marks for empty_body in empties for join in joins]
    # Cách đọc thêm của PR #8 (pipe_scope): như exact, nhưng khâu ống là shell con và đoạn sau `||` có thể không chạy.
    # `true && D=/srv/; x | D=/tmp/x/; rm -rf ${D}src` xoá /srv/src: cách đọc chặt bỏ cả phép gán sau `&&`, cách đọc lỏng
    # nhận phép gán trong ống. Thêm cách đọc rồi hợp nhãn nên không bớt nhãn của exact; chỉ đọc khi lệnh có `|`.
    if "|" in cmd:
        combos += [(join, True, False, True, raw_marks, strict_assign, empty_body, False, True, True, False, False, False)
                   for strict_assign in stricts for raw_marks in marks for empty_body in empties for join in joins]
    combos += [(join, True, False, True, raw_marks, False, True, False, True, False, True, False, False) for raw_marks in marks
               for join in joins]
    # Cách đọc pure (strict, biến chỉ đổi theo phép gán thuần chắc chạy ở shell này) xét sau cùng, chỉ lấy hợp: nó làm biến
    # thành không biết ở chỗ strict giữ giá trị (`echo D=x`, `local`, `((D=0))`, lệnh ghép...). Không có `$` thì env không
    # vào đoạn nào: không đọc.
    if "$" in cmd:
        combos += [(join, True, False, True, raw_marks, False, True, False, True, False, True, True, False) for raw_marks in marks
                   for join in joins]
    # Cách đọc bash (strict, nhận heredoc và here-string như bash: port vibrant-pascal 970114a) xét sau cùng, chỉ lấy hợp,
    # với env của strict và của pure. "`<<` này có mở heredoc không, thân tới đâu" sai được theo cả hai hướng (coi là heredoc
    # thì thân nuốt lệnh sau, không coi thì thân thành lệnh), mỗi cách sai ở bộ ca khác. Không có `<<` thì b như strict.
    if "<<" in cmd:
        combos += [(join, True, False, True, raw_marks, False, True, False, True, False, True, pure, True)
                   for pure in ((False, True) if "$" in cmd else (False,)) for raw_marks in marks for join in joins]
    return combos


def suspicious_labels(cmd, patterns, tool="Bash"):
    labels = []
    ifs = bool(re.search(r"\bIFS\b", cmd))  # IFS khác: giá trị của biến bị tách thành đích khác
    # Nhiều tổ hợp cho cùng danh sách đoạn (reading_key): chỉ đọc tổ hợp đầu của mỗi lớp, và mỗi đoạn chỉ so mẫu một lần.
    # Đoạn đã so thì so lại không thêm nhãn nào, nên nhãn và thứ tự nhãn y như khi đọc đủ mọi tổ hợp.
    bodies, read, segs = {}, set(), []
    for combo in reading_combos(cmd, tool):
        key = reading_key(cmd, tool, combo, bodies)
        if key not in read:
            read.add(key)
            segs += segments(cmd, tool, *combo)
    done = set()
    for seg in segs:
        if seg in done:
            continue
        done.add(seg)
        plain, full, ctx, subst = seg
        for rx, label in patterns:
            if label in labels or not re.search(rx, plain, re.IGNORECASE):
                continue
            # Đích worktree có được nhờ thay biến thì không tin: gán tạm `D=x lệnh` không đổi biến của shell mà ASSIGN vẫn ghi.
            if label == "xoá đệ quy" and benign_delete(full, ctx, worktree=not (subst or ifs), tool=tool):
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
