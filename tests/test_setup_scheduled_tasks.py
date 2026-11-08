"""Canh tĩnh `scripts/setup_scheduled_tasks.ps1` (CI không có PowerShell).

08/11: chuyển task tin mỗi giờ sang laptop. Script cũ luôn đăng ký đủ 3 task ⇒ chạy trên laptop là
laptop cũng chạy pipeline Daily/Weekend trên kho Dropbox chung (conflicted copy, brief trùng).
"""
from __future__ import annotations

import re
from pathlib import Path

PS1 = Path(__file__).resolve().parent.parent / "scripts" / "setup_scheduled_tasks.ps1"


def _src() -> str:
    return PS1.read_text(encoding="utf-8")


def test_only_news_alert_switch_declared_and_filters_to_news_task():
    s = _src()
    assert re.search(r"\[switch\]\$OnlyNewsAlert", s)
    block = s[s.index("if ($OnlyNewsAlert) {"):]
    assert 'Where-Object { $_.Name -eq "VnStock News Alert" }' in block.split("\n}\n")[0]


def test_only_and_no_news_alert_are_mutually_exclusive():
    s = _src()
    assert "if ($NoNewsAlert -and $OnlyNewsAlert)" in s
    excl = s.index("if ($NoNewsAlert -and $OnlyNewsAlert)")
    assert excl < s.index("if ($OnlyNewsAlert) {") < s.index("foreach ($task in $TaskDefinitions)")


def test_only_news_alert_never_unregisters_pipeline_tasks():
    s = _src()
    block = s[s.index("if ($OnlyNewsAlert) {"):s.index("# -NoNewsAlert:")]
    assert "Unregister-ScheduledTask" not in block


def test_write_host_strings_stay_ascii():
    # Windows PowerShell 5.1 đọc .ps1 không BOM theo ANSI ⇒ chữ có dấu trong chuỗi in ra bị vỡ.
    for line in _src().splitlines():
        if "Write-Host" in line or "Write-Error" in line:
            assert line.isascii(), line
