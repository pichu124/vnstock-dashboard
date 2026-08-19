"""
vnstock_ohlc_repair.py — Nới low/high cho bar TỰ MÂU THUẪN, thay vì cách ly nó
=============================================================================
Sinh từ số đo 19/08. Đếm `_meta/remediation_log.jsonl`: ~34.000 mục bị cách ly
với lý do gốc `low > min(open, close, high)` hoặc `high < max(open, close, low)`
— bar có giá thấp nhất CAO HƠN giá mở/đóng, hoặc giá cao nhất THẤP HƠN. Bất khả
về mặt định nghĩa.

Vòng lặp vô nghĩa mà nó tạo ra: hợp đồng loại bar → vào hàng đợi cách ly →
`auto_heal` gọi `refetch` → **cùng nguồn trả về cùng bar mâu thuẫn** → trượt
hợp đồng lần nữa. Đo được: 3.844 mục quét, **35 lành = 0,9%**, tốn 35,9 phút
mỗi đêm — 83% của bước `sync`.

Phép sửa và VÌ SAO nó không phải bịa số
---------------------------------------
    low  := min(low, open, close)
    high := max(high, open, close)

Giá trị mới KHÔNG phải giá tự nghĩ ra: nó là chính `open` hoặc `close` — mức
giá ĐÃ KHỚP trong phiên đó. Bar nói "giá thấp nhất là X" trong khi có lệnh khớp
ở mức thấp hơn X thì mâu thuẫn nằm ở con số X, không nằm ở lệnh đã khớp. Phép
sửa nhỏ nhất là NỚI biên để bao được thứ ta biết chắc đã xảy ra.

Trần `MAX_WIDEN_PCT`
-------------------
Biên độ dao động một phiên ở VN có TRẦN: HOSE ±7%, HNX ±10%, UPCoM ±15%. Nên
một bar thật không bao giờ cần nới quá ~15%. Cần nới hơn `MAX_WIDEN_PCT` (20%)
⇒ đây không phải bar dở, mà là bar HỎNG (feed lỗi, lẫn đơn vị) ⇒ **KHÔNG sửa**,
để hợp đồng loại và cách ly như cũ. Sửa bừa ở đó là tự tay vẽ ra một cây nến
râu dài không có thật.

An toàn
-------
* Hàm `repair_ohlc` THUẦN — không đọc/ghi đĩa, test được offline.
* Chỉ đụng hàng THỰC SỰ vi phạm; hàng hợp lệ trả về nguyên vẹn (idempotent).
* Bỏ qua hàng thiếu bất kỳ giá trị nào trong 4 cột (không đoán).
* Mỗi ca sửa được GHI VẾT (`_meta/ohlc_repairs.json`) + badge doctor, đúng nếp
  `unit_normalizations.json`: mọi lớp tự-sửa best-effort phải có đường soi lại.
* Tắt: `VNSTOCK_OHLC_REPAIR=0` → hành vi y như trước (bar mâu thuẫn bị cách ly).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime
from pathlib import Path

_OHLC = ("open", "high", "low", "close")
# Trần nới, theo tỉ lệ trên `close`. Xem docstring: biên độ phiên ở VN tối đa
# ±15% (UPCoM) nên 20% đã là ngoài mọi khả năng của một bar thật.
MAX_WIDEN_PCT = 0.20
# Giữ tối đa ngần này ca gần nhất trong vết — đủ để soi, không phình vô hạn.
_LOG_MAX = 500
_WRITE_LOCK = threading.Lock()


def enabled() -> bool:
    return os.environ.get("VNSTOCK_OHLC_REPAIR", "1") != "0"


def repair_ohlc(df, ticker: str = "?"):
    """Nới low/high cho các hàng tự mâu thuẫn. Trả `(df_mới, list_ca_sửa)`.

    Hàm THUẦN. `df` không bị sửa tại chỗ — trả bản sao khi có thay đổi, trả
    chính `df` khi không có gì để sửa (rẻ + idempotent).
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return df, []
    if any(c not in df.columns for c in _OHLC):
        return df, []

    vals = df[list(_OHLC)].apply(pd.to_numeric, errors="coerce")
    ok_row = vals.notna().all(axis=1) & (vals > 0).all(axis=1)
    if not ok_row.any():
        return df, []

    lo_target = vals[["open", "close", "low"]].min(axis=1)
    hi_target = vals[["open", "close", "high"]].max(axis=1)
    need_lo = ok_row & (vals["low"] > lo_target)
    need_hi = ok_row & (vals["high"] < hi_target)
    need = need_lo | need_hi
    if not need.any():
        return df, []

    # Trần nới: quá ngưỡng ⇒ bar HỎNG, để hợp đồng loại như cũ.
    widen = (
        (vals["low"] - lo_target).clip(lower=0)
        + (hi_target - vals["high"]).clip(lower=0)
    ) / vals["close"]
    within = widen <= MAX_WIDEN_PCT
    fixable = need & within
    if not fixable.any():
        return df, []

    out = df.copy()
    repairs = []
    for i in out.index[fixable]:
        rec = {"ticker": str(ticker).upper(),
               "widen_pct": round(float(widen.loc[i]) * 100, 4)}
        try:
            rec["time"] = str(pd.to_datetime(out.at[i, "time"]).date())
        except Exception:
            rec["time"] = "?"
        if need_lo.loc[i]:
            rec["low"] = [float(vals["low"].loc[i]), float(lo_target.loc[i])]
            out.at[i, "low"] = float(lo_target.loc[i])
        if need_hi.loc[i]:
            rec["high"] = [float(vals["high"].loc[i]), float(hi_target.loc[i])]
            out.at[i, "high"] = float(hi_target.loc[i])
        repairs.append(rec)
    return out, repairs


def log_path(warehouse_root: "Path | str") -> Path:
    return Path(warehouse_root) / "_meta" / "ohlc_repairs.json"


def load_repairs(warehouse_root: "Path | str") -> dict:
    """Vết đã ghi. Đọc hỏng → rỗng, KHÔNG ném (doctor gọi hàm này)."""
    try:
        p = log_path(warehouse_root)
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_repairs(warehouse_root: "Path | str", repairs: list,
                   now: "datetime | None" = None) -> None:
    """Ghi vết (nguyên tử, có khoá). Lỗi ghi KHÔNG được làm hỏng lượt sync."""
    if not repairs:
        return
    try:
        with _WRITE_LOCK:
            data = load_repairs(warehouse_root)
            events = list(data.get("events") or [])
            stamp = (now or datetime.now()).isoformat(timespec="seconds")
            events.extend({**r, "at": stamp} for r in repairs)
            data["events"] = events[-_LOG_MAX:]
            data["total"] = int(data.get("total") or 0) + len(repairs)
            p = log_path(warehouse_root)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                      default=str), encoding="utf-8")
            os.replace(tmp, p)
    except Exception:
        pass
