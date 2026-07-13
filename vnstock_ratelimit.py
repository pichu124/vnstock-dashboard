#!/usr/bin/env python3
"""vnstock_ratelimit.py — chịu đòn rate-limit của vnai (lớp quota vnstock).

Bẫy thật 2026-07-13: "Cập nhật giá" 8 luồng chết CỨNG ở 558/1.724 mã khi chạm
trần 500 req/phút (gói Golden). Nguyên nhân đã mổ tận nơi
(``vnai/beam/quota.py:313``): khi hết lượt retry nội bộ, vnai KHÔNG raise
Exception thường mà gọi ``sys.exit("Rate limit exceeded ... Process
terminated.")`` → ``SystemExit`` kế thừa ``BaseException``, xuyên thủng mọi
``except Exception`` per-ticker của updater; trong ThreadPoolExecutor nó được
``fut.result()`` re-raise ở luồng chính → sập cả tiến trình giữa chừng.

``call_with_rate_limit_retry(fn, ...)`` bọc MỘT call fetch: bắt cả SystemExit
lẫn exception rate-limit, đọc "Chờ X giây" trong message của vnai (fallback
61s), ngủ rồi gọi lại (mặc định 3 lượt chờ). Hết lượt → nâng thành
``RuntimeError`` (Exception thường) để vòng lặp per-ticker degrade thành 1 mã
lỗi thay vì chết cả run. Lỗi KHÔNG phải rate-limit (kể cả SystemExit thật /
KeyboardInterrupt) re-raise nguyên vẹn.

Cùng họ với fix PanicException trong vnstock_doctor.run_checks — bài học
chung: thư viện ngoài có thể ném BaseException ngoài Exception.
"""
from __future__ import annotations

import re
import time

# Message vnai: "• Chờ 54 giây để tiếp tục (Wait to retry)" — bắt cả EN đề phòng.
_WAIT_RE = re.compile(r"(?:Chờ|Wait)\D{0,20}?(\d+)\s*(?:giây|seconds?)", re.I)
_DEFAULT_WAIT = 61          # trần theo PHÚT → hết cửa sổ chắc chắn sau 60s
_MAX_WAIT = 300             # vnai còn trần theo GIỜ (retry_after tới 3600) — cap lại


def is_rate_limit(exc: BaseException) -> bool:
    """Nhận diện lỗi rate-limit của vnai qua message (cả bản sys.exit)."""
    s = str(exc)
    return "rate limit" in s.lower() or "GIỚI HẠN API" in s


def wait_seconds(exc: BaseException, default: int = _DEFAULT_WAIT) -> int:
    """Số giây nên chờ — parse 'Chờ X giây' từ message vnai, +2s đệm."""
    m = _WAIT_RE.search(str(exc))
    if m:
        try:
            return max(1, min(int(m.group(1)) + 2, _MAX_WAIT))
        except ValueError:
            pass
    return default


def call_with_rate_limit_retry(fn, *args, retries: int = 3, on_wait=None, **kwargs):
    """Gọi ``fn(*args, **kwargs)``; đụng rate-limit → ngủ theo hướng dẫn trong
    message rồi thử lại, tối đa ``retries`` lượt chờ.

    ``on_wait(seconds, attempt)`` (tùy chọn) được gọi trước mỗi lần ngủ — để
    updater in thông báo; helper tự nó không đụng console (an toàn gọi từ
    worker thread).
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except KeyboardInterrupt:              # Ctrl+C của user: thoát thật
            raise
        except BaseException as e:  # noqa: BLE001 — SystemExit của vnai KHÔNG phải Exception
            if not is_rate_limit(e):
                raise
            attempt += 1
            if attempt > retries:
                # Exception THƯỜNG để except Exception per-ticker bắt được —
                # 1 mã lỗi, run vẫn sống.
                raise RuntimeError(
                    f"rate limit không hạ sau {retries} lượt chờ: {str(e)[:120]}"
                ) from e
            w = wait_seconds(e)
            if on_wait is not None:
                try:
                    on_wait(w, attempt)
                except Exception:
                    pass
            time.sleep(w)
