"""Dựng chuỗi lệnh PowerShell cho nút "chạy trong cửa sổ mới" của dashboard.

Tách khỏi `vnstock_dashboard.py` (12/08). CHỈ phần dựng CHUỖI nằm ở đây — phần
`subprocess.Popen` vẫn ở lại dashboard vì nó cần `Path(__file__).parent` của
chính file dashboard làm cwd. Nhờ vậy test chạy được trên Linux CI mà không
cần Windows, và không còn replica chép tay trong `tests/test_dashboard.py`.

Mỗi step là dict: `{"label": str, "args": [str, ...], "stop_on_error": bool}`.
"""
from __future__ import annotations

_STOP_ON_ERROR_GUARD = (
    "if ($LASTEXITCODE -ne 0) { "
    "Write-Host 'Previous step failed' -ForegroundColor Red; "
    "Read-Host 'Nhan Enter de dong cua so'; exit 1 }"
)


def build_ps_command(commands: list, python_exe: str) -> str:
    """Trả chuỗi `-Command` cho powershell.exe chạy tuần tự các step.

    Guard dừng-khi-lỗi KHÔNG chèn sau step cuối (không còn gì để dừng) và
    không chèn cho step khai `stop_on_error=False`.
    """
    parts = [
        "$env:PYTHONIOENCODING='utf-8'",
        "chcp 65001 | Out-Null",
    ]
    for i, cmd in enumerate(commands):
        parts.append(f"Write-Host '=== {cmd['label']} ===' -ForegroundColor Cyan")
        quoted = " ".join(f"'{a}'" for a in cmd["args"])
        parts.append(f"& '{python_exe}' {quoted}")
        if cmd.get("stop_on_error", True) and i < len(commands) - 1:
            parts.append(_STOP_ON_ERROR_GUARD)
    parts.append("Write-Host ''")
    parts.append("Read-Host 'Hoan tat. Nhan Enter de dong cua so'")
    return "; ".join(parts)
