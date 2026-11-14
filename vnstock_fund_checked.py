"""Sổ "mã này được NGUỒN TRẢ LỜI lần cuối ngày nào" của updater cơ bản (14/11).

Vì sao tồn tại: lượt `fundamentals --force` đủ 1.754 mã trên vnstock thế hệ 6 mất
~5 giờ (đo 🖥️ 14/11: 5,8 mã/phút với `--workers 4 --delay 1`), còn trần task Weekend
là 180′ ⇒ tuần nào cũng bị cắt ở mã thứ ~850. Danh sách mã xếp theo bảng chữ cái nên
chỗ cắt luôn là MỘT chỗ: nửa sau bảng chữ cái không bao giờ được cập nhật.

Cách chữa là đổi THỨ TỰ chạy, không nâng trần: chưa kiểm bao giờ → cũ nhất → mới
nhất. Bị cắt ở đâu thì lượt sau đi tiếp phần còn lại; hai thứ Bảy phủ hết kho.

Vì sao cần sổ riêng mà không dùng cột `updated_at` của `fundamentals.parquet`: mã mà
nguồn trả RỖNG nhưng kho đã có số ("giữ data cũ" — 160 mã lượt 14/11) thì dòng
parquet KHÔNG đổi, `updated_at` đứng im ở ngày cũ ⇒ chỉ dựa cột đó là chúng chen lên
đầu hàng mỗi tuần. "Được kiểm" ở đây = nguồn đã trả lời (có số HOẶC rỗng). Mã LỖI
không được ghi: lượt sau thử lại sớm.

File `fundamentals_checked.json` nằm CẠNH `fundamentals.parquet` (trong kho ⇒ đi
Dropbox; chỉ updater cơ bản ghi). Dạng phẳng `{mã: "YYYY-MM-DD"}`. Mất sổ không mất
dữ liệu — lượt kế rơi về `updated_at` rồi tự dựng lại.

Module THUẦN + đọc/ghi sổ, không import updater: doctor dùng chung được mà không
kéo theo rich / vnstock.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

LEDGER_NAME = "fundamentals_checked.json"


def load(path: "Path | str") -> dict[str, str]:
    """Đọc sổ. Chưa có / hỏng / sai dạng ⇒ `{}` (coi như chưa kiểm mã nào)."""
    import json
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {t: d for t, d in raw.items()
            if isinstance(t, str) and t and isinstance(d, str) and d}


def save(checked: dict[str, str], path: "Path | str") -> None:
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(dict(sorted(checked.items())), path)


def last_checked(existing, checked: dict[str, str]) -> dict[str, str]:
    """Ngày kiểm gần nhất của từng mã = bản MỚI HƠN giữa sổ và `updated_at` của kho.

    `existing` là DataFrame `fundamentals.parquet` (có thể rỗng / thiếu cột). Mã không
    có ngày nào thì KHÔNG có trong kết quả — `fetch_order` xếp chúng lên đầu.
    """
    out = dict(checked)
    cols = getattr(existing, "columns", ())
    if "ticker" in cols and "updated_at" in cols:
        for ticker, day in zip(existing["ticker"], existing["updated_at"]):
            if isinstance(ticker, str) and isinstance(day, str) and day > out.get(ticker, ""):
                out[ticker] = day
    return out


def fetch_order(tickers: Iterable[str], last: dict[str, str]) -> list[str]:
    """Chưa kiểm bao giờ → cũ nhất → mới nhất; cùng ngày thì theo bảng chữ cái."""
    return sorted(tickers, key=lambda t: (last.get(t, ""), t))


def _age_days(day: str, today: date) -> "int | None":
    try:
        return (today - date.fromisoformat(day[:10])).days
    except ValueError:
        return None


def checked_within(tickers: Iterable[str], last: dict[str, str],
                   days: int, today: date) -> set[str]:
    """Mã đã được kiểm trong `days` ngày gần đây (`days=1` = kiểm HÔM NAY).

    `days <= 0` ⇒ rỗng. Mã chưa kiểm hoặc ngày không đọc được thì không bao giờ
    nằm trong tập này (thà hỏi lại nguồn còn hơn bỏ sót)."""
    if days <= 0:
        return set()
    out = set()
    for t in tickers:
        age = _age_days(last.get(t, ""), today)
        if age is not None and age < days:
            out.add(t)
    return out


def stale_count(tickers: Iterable[str], last: dict[str, str],
                max_age_days: int, today: date) -> int:
    """Số mã chưa từng được kiểm HOẶC kiểm lần cuối cách đây hơn `max_age_days` ngày."""
    n = 0
    for t in tickers:
        age = _age_days(last.get(t, ""), today)
        if age is None or age > max_age_days:
            n += 1
    return n
