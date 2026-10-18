"""Đọc/ghi watchlist — STATE CỦA USER, không phải cache dựng lại được.

Tách khỏi `vnstock_dashboard.py` (12/08) và nhân tiện vá luôn một lỗ cùng họ
với đợt "ghi nguyên tử": `save_watchlist` cũ mở `open(w)` → cắt file về 0 TRƯỚC
khi ghi nội dung mới. Chết giữa chừng (máy tắt, Ctrl-C, đĩa đầy) = watchlist
user tự tay dựng BIẾN MẤT. Nay đi qua `write_json_atomic` (tmp + os.replace).
`load_watchlist` cũng thôi nuốt file hỏng thành `[]`: nút Thêm sẽ ghi đè cả
watchlist bằng `[] + mã mới` rồi Dropbox đẩy sang máy kia — nay raise để UI
khoá ghi.

File này nằm trong lưới `_MUST_BE_ATOMIC` của `tests/test_atomic_writes.py`.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from vnstock_parquet_io import write_json_atomic


def load_watchlist(path: "Path | str") -> list:
    """Đọc danh sách mã. Thiếu file ⇒ `[]` (hợp lệ). File hỏng/sai dạng/không đọc
    được ⇒ raise (OSError/ValueError) — caller phải khoá ghi, không coi là rỗng."""
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tickers = data.get("tickers", []) if isinstance(data, dict) else None
    if not (isinstance(tickers, list) and all(isinstance(t, str) for t in tickers)):
        raise ValueError('sai định dạng: cần object {"tickers": ["VCB", ...]}')
    return tickers


def save_watchlist(path: "Path | str", tickers) -> None:
    """Ghi danh sách mã đã khử trùng lặp + sắp xếp, theo kiểu nguyên tử."""
    write_json_atomic(
        {"tickers": sorted(set(tickers)), "updated_at": datetime.now().isoformat()},
        path,
    )
