"""Marker "pipeline đang chạy" — chặn bấm chạy trùng giữa hai máy dùng chung kho.

Kho đi Dropbox (CLAUDE.md, hệ quả #3): bấm 📥/🧩/🚀 ở laptop trong lúc task
18:00 của desktop đang sync là hai máy cùng ghi `prices/` ⇒ conflicted copy.
`run.py all|sync` (cả task Daily) và nút 📥 (chạy script qua
`python vnstock_pipeline_marker.py <script.py> [args…]`) ghi
`_meta/pipeline_running.json` lúc bắt đầu, xoá ở `finally`; dashboard đọc để
vô hiệu 3 nút. Best-effort: ghi/xoá lỗi không làm hỏng pipeline.
Kill-switch: VNSTOCK_PIPELINE_MARKER=0 (máy này thôi ghi marker).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

MARKER_NAME = "pipeline_running.json"
ENV_SWITCH = "VNSTOCK_PIPELINE_MARKER"
# Trần task Daily 240 phút + 1 giờ dư. Quá mốc = marker mồ côi (đóng cửa sổ,
# tắt máy giữa chừng ⇒ `finally` không chạy) ⇒ không chặn nữa.
STALE_AFTER_HOURS = 5
DEFAULT_WAREHOUSE = Path(__file__).resolve().parent / "data_warehouse"
_OFF = ("0", "false", "off", "no")


def marker_path(warehouse) -> Path:
    return Path(warehouse) / "_meta" / MARKER_NAME


def read_marker(path) -> "dict | None":
    """None khi không có file hoặc file hỏng — marker hỏng không được chặn nút."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_pipeline_running(marker, now: datetime) -> "tuple[bool, str]":
    if not isinstance(marker, dict):
        return False, "không có marker"
    try:
        started = datetime.fromisoformat(str(marker["started_at"]))
    except (KeyError, ValueError):
        return False, "marker thiếu/sai started_at — bỏ qua"
    if now - started > timedelta(hours=STALE_AFTER_HOURS):
        return False, (f"marker từ {started:%d/%m %H:%M} quá {STALE_AFTER_HOURS} giờ "
                       f"— coi như mồ côi")
    return True, (f"Pipeline đang chạy trên máy {marker.get('machine') or '?'} "
                  f"từ {started:%H:%M} (lệnh {marker.get('command') or '?'})")


@contextmanager
def held(warehouse, command: str):
    """Giữ marker trong suốt khối `with`. Ghi lỗi ⇒ không xoá (có thể là marker
    của máy kia)."""
    # ponytail: không so pid/máy trước khi xoá — chỉ lệch khi user tự tick
    # "Vẫn chạy" cho hai lượt chồng nhau; cần thì so `pid`+`machine` ở đây.
    path = marker_path(warehouse)
    wrote = False
    if (os.environ.get(ENV_SWITCH) or "1").strip().lower() not in _OFF:
        try:
            from vnstock_parquet_io import write_json_atomic
            from vnstock_rollup import get_hostname
            write_json_atomic({
                "machine": get_hostname(), "pid": os.getpid(),
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "command": command,
            }, path)
            wrote = True
        except Exception as exc:
            print(f"[pipeline-marker] không ghi được {path}: {exc}", file=sys.stderr)
    try:
        yield
    finally:
        if wrote:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"[pipeline-marker] không xoá được {path}: {exc}", file=sys.stderr)


def main(argv: "list[str] | None" = None) -> int:
    """`python vnstock_pipeline_marker.py <script.py> [args…]` — chạy script
    trong lúc giữ marker, trả nguyên exit code của nó (nút 📥 của dashboard)."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: python vnstock_pipeline_marker.py <script.py> [args...]",
              file=sys.stderr)
        return 2
    with held(DEFAULT_WAREHOUSE, " ".join(argv)):
        return subprocess.call([sys.executable, *argv])


if __name__ == "__main__":
    sys.exit(main())
