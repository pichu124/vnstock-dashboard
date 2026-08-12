"""vnstock_parquet_io.py — ghi/đọc Parquet AN TOÀN cho kho giá.

BÀI HỌC AUDIT 06/08/2026 (lỗi CRITICAL, chưa từng nổ nhưng đã sẵn sàng nổ)
──────────────────────────────────────────────────────────────────────────
`updater`/`rollup` ghi THẲNG `pq.write_table(...)` vào `prices.parquet`:
lệnh này mở file thật, cắt về 0 byte rồi chép nội dung mới — trong khoảnh
khắc đó file trên đĩa DỞ DANG. Process chết đúng lúc (Task Scheduler
`ExecutionTimeLimit 120'` kill CỨNG, máy tắt/ngủ giữa pipeline — kịch bản
thường trực vì lịch chạy dùng StartWhenAvailable, Ctrl+C, mất điện) →
file cụt.

Lần chạy sau, `_read_year` gặp file hỏng lại `except: continue` → KHÔNG
phân biệt được "file hỏng" với "mã chưa có data" → merge ghi đè canonical
chỉ với vài dòng hôm nay → MẤT CẢ NĂM lịch sử, im lặng (không lỗi, không
log). Tệ hơn: file mới mang ngày hôm nay nên `_get_last_date` báo
"up-to-date" → KHÔNG BAO GIỜ refetch. Mất vĩnh viễn.

Hai lớp chống trong module này
──────────────────────────────
1. `write_table_atomic` — ghi ra `.tmp` rồi `os.replace`. `os.replace` là
   thao tác NGUYÊN TỬ của OS: hoặc còn nguyên file cũ, hoặc đã là file mới,
   KHÔNG BAO GIỜ nửa vời. Pattern này repo ĐÃ dùng đúng ở
   `vnstock_wss._flush_bars` và `vnstock_rollup.write_pipeline_status` —
   module này gom về một chỗ thay vì chép lần thứ ba.

2. `read_year_frames` — file đọc lỗi KHÔNG bị nuốt im lặng nữa. Xử lý khác
   nhau theo caller vì khả năng TỰ LÀNH khác nhau:

   * `strict=False` (updater): updater dò ngày cuối bằng `_get_last_date`,
     hàm này bỏ qua file không đọc được → rơi về năm trước → `fetch_from`
     phủ NGUYÊN NĂM → nó tự tải lại đủ từ API. Nên ở đây cách ly file hỏng
     (đổi tên `.corrupt-<ts>`) + cảnh báo rồi ĐI TIẾP: lần ghi ngay sau đó
     chính là bản đầy đủ vừa refetch → tự lành.

   * `strict=True` (rollup): rollup CHỈ có bar hôm nay, ghi tiếp là tạo ra
     đúng file 1 dòng gây mất data. Nên raise `CorruptWarehouseFile` để
     caller BỎ QUA ticker-year đó. Cố ý KHÔNG đổi tên file hỏng: giữ
     nguyên làm "dây bẫy" để mọi lần rollup sau đều dừng, cho tới khi
     updater (chạy TRƯỚC rollup trong `run.py sync`) cách ly + refetch.
     Đổi tên ở đây sẽ khiến lần rollup kế tiếp thấy thư mục rỗng và ghi
     đúng file 1 dòng ta đang muốn tránh.

File không phải canonical (bản "conflicted copy" của Dropbox) hỏng thì chỉ
cách ly + cảnh báo ở CẢ HAI chế độ — nó không phải nguồn chân lý.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

# Tên file nguồn-chân-lý trong mỗi year-dir. Mọi file .parquet khác cạnh nó
# là bản sao Dropbox đẻ ra, được _read_year gộp vào rồi xoá khi ghi.
CANONICAL_NAME = "prices.parquet"


class CorruptWarehouseFile(Exception):
    """File parquet CANONICAL không đọc được — caller phải bỏ qua ticker-year
    này, tuyệt đối không ghi đè như thể chưa có dữ liệu."""


def write_table_atomic(table, out_path: "Path | str",
                       compression: str = "snappy") -> None:
    """Ghi `table` ra `out_path` theo kiểu tmp-rồi-tráo (xem docstring module).

    Tên tạm mang cả pid lẫn thread-id nên nhiều tiến trình/luồng ghi cùng lúc
    không giẫm lên nhau, và KHÔNG kết thúc bằng `.parquet` nên không bao giờ
    bị `_read_year` (glob `*.parquet`) nhặt nhầm thành dữ liệu.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(
        f"{out_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        pq.write_table(table, str(tmp), compression=compression)
        os.replace(str(tmp), str(out_path))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def write_json_atomic(payload, out_path: "Path | str", *, indent: int = 2) -> None:
    """Ghi JSON theo kiểu tmp-rồi-tráo — anh em của `write_table_atomic`.

    Quét 12/08 cho thấy repo đã lặp pattern tmp+os.replace ở ~15 module (ai
    cũng tự viết lại), còn vài chỗ giữ STATE thì ghi thẳng. Gom về một chỗ:
    serialize TRƯỚC khi đụng đĩa, nên payload hỏng cũng không cắt cụt file cũ.
    """
    out_path = Path(out_path)
    blob = json.dumps(payload, ensure_ascii=False, indent=indent, default=str)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(
        f"{out_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(blob, encoding="utf-8")
        os.replace(str(tmp), str(out_path))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _quarantine(pf: Path) -> "str | None":
    """Đổi tên file hỏng thành `<tên>.corrupt-<ts>`. None nếu không đổi được."""
    dest = pf.with_name(
        f"{pf.name}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    try:
        os.replace(str(pf), str(dest))
        return dest.name
    except Exception:
        return None


def read_year_frames(year_dir: Path, *, strict: bool) -> list:
    """Đọc MỌI `*.parquet` trong year-dir (cũ→mới theo mtime) → list DataFrame.

    Gộp mọi file vì Dropbox có thể đẻ "conflicted copy" mang data mới hơn
    file chính; đọc mỗi file chính là mất phần data nằm ở file kia.

    File hỏng: cách ly + cảnh báo. Nếu file hỏng là CANONICAL và
    ``strict=True`` → raise `CorruptWarehouseFile` (xem docstring module).
    """
    if not year_dir.exists():
        return []
    frames: list = []
    for pf in sorted(year_dir.glob("*.parquet"), key=lambda p: p.stat().st_mtime):
        try:
            df = pq.read_table(str(pf)).to_pandas()
        except Exception as e:
            is_canonical = pf.name == CANONICAL_NAME
            if is_canonical and strict:
                # Giữ nguyên file làm dây bẫy — KHÔNG cách ly (docstring module)
                print(f"  [warehouse] ⛔ {pf} HỎNG ({type(e).__name__}) — bỏ qua "
                      f"để khỏi ghi đè mất lịch sử; updater sẽ tải lại cả năm")
                raise CorruptWarehouseFile(
                    f"{pf}: {type(e).__name__}: {str(e)[:120]}") from e
            moved = _quarantine(pf)
            print(f"  [warehouse] ⚠ {pf} HỎNG ({type(e).__name__}) → cách ly "
                  f"{moved or '(không đổi tên được)'}"
                  + (" — sẽ tải lại cả năm từ API" if is_canonical else ""))
            continue
        try:
            df["time"] = pd.to_datetime(df["time"]).dt.date
        except Exception as e:
            # Đọc được nhưng cột time lạ: bỏ qua frame, KHÔNG cách ly (file
            # có thể vẫn dùng được cho mục đích khác — không tự tiện đổi tên).
            print(f"  [warehouse] ⚠ {pf}: cột time không parse được "
                  f"({type(e).__name__}) — bỏ qua file này")
            continue
        frames.append(df)
    return frames
