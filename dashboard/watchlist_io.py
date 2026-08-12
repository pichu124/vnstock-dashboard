"""Đọc/ghi watchlist — STATE CỦA USER, không phải cache dựng lại được.

Tách khỏi `vnstock_dashboard.py` (12/08) và nhân tiện vá luôn một lỗ cùng họ
với đợt "ghi nguyên tử": `save_watchlist` cũ mở `open(w)` → cắt file về 0 TRƯỚC
khi ghi nội dung mới. Chết giữa chừng (máy tắt, Ctrl-C, đĩa đầy) = watchlist
user tự tay dựng BIẾN MẤT, và `load_watchlist` nuốt JSONDecodeError trả `[]`
nên mất im lặng. Nay đi qua `write_json_atomic` (tmp + os.replace).

File này nằm trong lưới `_MUST_BE_ATOMIC` của `tests/test_atomic_writes.py`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from vnstock_parquet_io import write_json_atomic

log = logging.getLogger(__name__)


def load_watchlist(path: "Path | str") -> list:
    """Đọc danh sách mã. Trả `[]` khi thiếu file / file hỏng (đã log rõ lý do)."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("tickers", [])
    except (OSError, PermissionError) as e:
        log.warning("Không đọc được watchlist (%s): %s", path, e)
    except json.JSONDecodeError as e:
        log.error("Watchlist JSON hỏng (%s): %s", path, e)
    return []


def save_watchlist(path: "Path | str", tickers) -> None:
    """Ghi danh sách mã đã khử trùng lặp + sắp xếp, theo kiểu nguyên tử."""
    write_json_atomic(
        {"tickers": sorted(set(tickers)), "updated_at": datetime.now().isoformat()},
        path,
    )
