"""
vnstock_price_fallback.py — Lưới đỡ nguồn giá: VCI (chính) → KBS (fallback)
===========================================================================
Sinh từ VCI outage tối 17/07 (playbook ⚡ + bảng xếp hạng `vnstock_source_probe`
trong CLAUDE.md): VCI có "giờ ốm" (khung ~21h, backend query treo 30s+/call),
KBS là ứng viên duy nhất đủ chuẩn (12/12 probe + index, 0.4s/call, bar đủ
phiên). User chốt "làm fallback đi" 17/07.

3 mảnh THUẦN (zero vnstock — updater import và wire):
  1. `CircuitBreaker` — thread-safe (updater chạy 8 worker): N mã LIÊN TIẾP
     lỗi mạng → MỞ mạch = bỏ qua VCI đi thẳng KBS (hết cảnh cày 60-90s/mã ×
     1724 mã); đang mở thì mỗi `probe_every` mã cho 1 lượt thử lại VCI —
     server hồi là tự ĐÓNG mạch quay về nguồn chính.
  2. `is_outage_error` — CHỈ lỗi dạng mạng/timeout mới tính vào breaker
     (mã lạ/symbol lỗi là chuyện riêng của mã đó, không phải outage).
  3. `reconcile_fallback_df` — chốt an toàn TRƯỚC KHI GHI KHO: bar overlap
     (ngày cuối warehouse, updater vốn refetch inclusive) phải KHỚP close
     warehouse. Lệch ~×1000 → đơn vị VND thô, chia 1000 cả OHLC; sau chuẩn
     hoá còn lệch > `_MAX_DIVERGENCE_PCT` → TỪ CHỐI (khác adjustment basis
     cổ tức — ghi bừa là hỏng chuỗi giá; giữ kho cũ, VCI tự lành sau).
     Không có bar overlap để đối chiếu → cũng từ chối (thà thiếu 1 ngày).

Tắt toàn bộ (hành vi y như trước): `VNSTOCK_PRICE_FALLBACK=0`.
"""

from __future__ import annotations

import os
import threading

FALLBACK_SOURCE = "KBS"            # ứng viên #1 theo probe 17/07 (đổi tại đây)
_OPEN_AFTER = 5                    # N mã lỗi mạng liên tiếp → mở mạch
_PROBE_EVERY = 25                  # đang mở: mỗi N mã thử lại VCI 1 lượt
_MAX_DIVERGENCE_PCT = 8.0          # lệch close overlap quá đây → từ chối data


def enabled() -> bool:
    return os.environ.get("VNSTOCK_PRICE_FALLBACK", "1") != "0"


_OUTAGE_TOKENS = (
    "timed out", "timeout", "connection", "retryerror", "max retries",
    "temporarily unavailable", "connection aborted", "connection reset",
    "unreachable", "502", "503", "504",
)


def is_outage_error(msg: str) -> bool:
    """Lỗi dạng MẠNG/OUTAGE (tính vào breaker + đáng thử fallback) hay lỗi
    riêng của mã (không)?"""
    low = (msg or "").lower()
    return any(t in low for t in _OUTAGE_TOKENS)


class CircuitBreaker:
    """Mạch ngắt dùng chung giữa các worker thread của updater."""

    def __init__(self, open_after: int = _OPEN_AFTER,
                 probe_every: int = _PROBE_EVERY):
        self.open_after = open_after
        self.probe_every = probe_every
        self._lock = threading.Lock()
        self._fails = 0
        self._open = False
        self._since_probe = 0

    def reset(self) -> None:
        with self._lock:
            self._fails = 0
            self._open = False
            self._since_probe = 0

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def allow_primary(self) -> bool:
        """Được thử nguồn CHÍNH không? Mạch đóng → luôn được; mạch mở → chỉ
        lượt probe định kỳ (mỗi `probe_every` mã) để phát hiện VCI hồi."""
        with self._lock:
            if not self._open:
                return True
            self._since_probe += 1
            if self._since_probe >= self.probe_every:
                self._since_probe = 0
                return True
            return False

    def record_ok(self) -> bool:
        """Nguồn chính trả lời OK. Trả True nếu mạch VỪA ĐÓNG LẠI (hồi phục
        sau outage — caller in log)."""
        with self._lock:
            self._fails = 0
            if self._open:
                self._open = False
                return True
            return False

    def record_fail(self) -> bool:
        """Nguồn chính lỗi MẠNG. Trả True nếu mạch VỪA MỞ (caller in log)."""
        with self._lock:
            self._fails += 1
            if not self._open and self._fails >= self.open_after:
                self._open = True
                self._since_probe = 0
                return True
            return False


BREAKER = CircuitBreaker()          # singleton — run_update reset() đầu mỗi run


def reconcile_fallback_df(df, wh_close, overlap_date,
                          max_divergence_pct: float = _MAX_DIVERGENCE_PCT):
    """Đối chiếu df fallback với warehouse TRƯỚC khi ghi.

    Trả (df_đã_chuẩn_hoá, note) khi ĐẠT — note "" hoặc "đơn vị VND thô…";
    (None, lý_do) khi TỪ CHỐI. df rỗng → (df, "") — caller xử no_new_data.
    """
    if df is None or getattr(df, "empty", True):
        return df, ""
    if wh_close is None or wh_close <= 0:
        return None, "không đọc được close warehouse để đối chiếu"
    row = df[df["time"] == overlap_date]
    if row.empty:
        return None, f"{FALLBACK_SOURCE} không trả bar {overlap_date} để đối chiếu"
    v = float(row["close"].iloc[0])
    if v <= 0:
        return None, f"bar đối chiếu close={v} không hợp lệ"
    ratio = v / float(wh_close)
    note = ""
    if 500 < ratio < 2000:                          # VND thô vs nghìn VND
        df = df.copy()
        for c in ("open", "high", "low", "close"):
            if c in df.columns:
                df[c] = df[c] / 1000.0
        ratio /= 1000.0
        note = "đơn vị VND thô → đã chia 1000"
    if abs(ratio - 1) * 100 > max_divergence_pct:
        return None, (f"close {overlap_date} lệch {abs(ratio - 1) * 100:.1f}% "
                      "vs warehouse (khác adjustment basis?) — giữ kho cũ")
    return df, note
