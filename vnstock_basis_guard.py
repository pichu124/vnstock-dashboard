"""
vnstock_basis_guard.py — Chặn LỆCH CƠ SỞ ngay tại đường ghi chính (V1)
======================================================================
Sinh từ ca 19/08: quét `probe_price_basis --sweep` ra **70/159 mã thanh khoản
(44%) lệch cơ sở**, gần trọn VN30, vách rải đúng mùa chia cổ tức 03-08/2026.

Cơ chế gây lỗi, đã dựng lại được từng bước:
  * Nguồn back-adjust TOÀN chuỗi sau mỗi sự kiện quyền.
  * `update_ticker` chỉ fetch từ `last_date` — KHÔNG có đường nạp lại lịch sử.
  * Merge `keep="last"` thay bar `last_date` bằng bar CƠ SỞ MỚI rồi nối tiếp,
    còn mọi bar cũ hơn giữ CƠ SỞ CŨ ⇒ sinh đúng MỘT bậc tại `last_date`, im
    lặng, không log, không cảnh báo.
Hậu quả: backtest bắc qua bậc thấy một cú rơi/nhảy KHÔNG CÓ THẬT. Vì sao không
ai thấy suốt bao lâu: `check_unit_continuity` nhìn VÁCH GIÁ (≥30%) nên mù —
giá vẫn liền mạch, vẫn khớp giá live, mã vẫn được báo "sạch".

Vì sao đặt guard ở ĐÂY chứ không ở bộ quét: quét là phát hiện SAU, mỗi mùa
quyền lại phải chữa lại ngần ấy mã. Đây là chỗ DUY NHẤT biết được "kho trước
khi ghi" và "nguồn sau khi ghi" cùng lúc.

Ba mảnh THUẦN (zero vnstock/pandas — updater import và wire):
  1. `enabled()` — kill-switch `VNSTOCK_BASIS_GUARD=0`, đúng nếp mọi tự-động
     khác trong repo.
  2. `check_basis` — hàm THUẦN: so trung vị tỉ lệ kho/nguồn trên vùng chồng
     lấn. Bỏ HẲN bar `last_date` khỏi phép so vì đúng bar đó có thể DỞ DANG
     (updater từng chạy trong phiên → VCI trả daily bar partial). Bar dở là
     nguồn báo động giả duy nhất đáng kể ở ngưỡng 1,2%.
  3. `record_drift` / `load_pending` — sổ mã bị cách ly, ghi NGUYÊN TỬ, để
     doctor dựng badge và người biết chữa mã nào.

Xử lý khi phát hiện: **CÁCH LY + CẢNH BÁO, KHÔNG tự ghi đè.** Sync chạy 3h
sáng không ai nhìn; tự động viết lại 20 năm lịch sử lúc đó là đúng loại hành
động không nên tự làm. Bỏ một ngày dữ liệu của một mã là chuyện phục hồi
được (chữa xong lần sync sau tự lấy lại); một bậc giả im lặng thì không.

Guard chỉ kêu trong ~`LOOKBACK_DAYS` ngay sau sự kiện quyền — sau đó bar gần
đây của kho đã ở cơ sở mới nên tỉ lệ về 1.0 và guard im. Tức bật guard trên
máy có kho CHƯA chữa cũng KHÔNG làm 70 mã ngừng cập nhật: nó bắt đúng khoảnh
khắc lệch sinh ra, không bắt di chứng cũ.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path

# Updater chạy 8 worker trên cùng tiến trình — hai mã cùng phát hiện lệch
# trong một nhịp là chuyện có thật vào mùa quyền. Ghi nguyên tử chống được
# file cụt nhưng KHÔNG chống được lost-update (đọc-sửa-ghi), mà sổ cách ly
# mất một dòng là mất đúng thứ nó sinh ra để giữ.
_WRITE_LOCK = threading.Lock()

# Nới cửa sổ fetch lùi lại ngần này NGÀY LỊCH để có vùng chồng lấn mà đối
# chiếu. Không tốn thêm lần gọi mạng nào — cùng một call, chỉ khác tham số
# `start`. 30 ngày lịch ≈ 20 phiên, dư cho trung vị.
LOOKBACK_DAYS = 30
# Dưới ngần này bar chồng lấn thì KHÔNG kết luận gì (mã mới niêm yết, mã
# thanh khoản thấp nghỉ giao dịch dài). Thà im còn hơn báo động trên 2 bar.
MIN_BARS = 5
# Cùng ngưỡng với `probe_price_basis.SAME_BASIS_TOL` — hai bên phải khớp,
# nếu không sẽ có mã guard cho qua mà bộ quét lại gắn cờ (hoặc ngược lại).
TOL = 0.012


def enabled() -> bool:
    return os.environ.get("VNSTOCK_BASIS_GUARD", "1") != "0"


def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def check_basis(wh_closes: dict, src_closes: dict, last_date: date,
                tol: float = TOL, min_bars: int = MIN_BARS) -> dict:
    """Nguồn có vừa đổi cơ sở điều chỉnh dưới chân kho không?

    Hàm THUẦN. `wh_closes` / `src_closes`: {date: close}. Chỉ so các bar
    **trước** `last_date` — bar `last_date` có thể dở dang ở phía kho.

    verdict:
      * `no_overlap`    — chưa đủ bar chung để phán, cứ ghi như cũ.
      * `aligned`       — cùng cơ sở, ghi bình thường.
      * `basis_changed` — nguồn đã rebase; ghi tiếp là sinh bậc giả.
    """
    pairs = [(d, wh_closes[d], src_closes[d])
             for d in sorted(set(wh_closes) & set(src_closes))
             if d < last_date
             and _pos(wh_closes[d]) and _pos(src_closes[d])]
    if len(pairs) < min_bars:
        return {"verdict": "no_overlap", "n": len(pairs)}
    ratios = [float(w) / float(s) for _, w, s in pairs]
    r = _median(ratios)
    out = {"ratio": r, "n": len(pairs),
           "first": pairs[0][0].isoformat(), "last": pairs[-1][0].isoformat()}
    if abs(r - 1.0) <= tol:
        out["verdict"] = "aligned"
        return out
    out["verdict"] = "basis_changed"
    out["pct"] = (r - 1.0) * 100.0
    return out


def _pos(v) -> bool:
    try:
        return float(v) > 0
    except Exception:
        return False


def pending_path(warehouse_root: Path) -> Path:
    return Path(warehouse_root) / "_meta" / "basis_drift_pending.json"


def load_pending(warehouse_root: Path) -> dict:
    """Sổ mã đang bị cách ly. Đọc hỏng → rỗng, KHÔNG ném (doctor gọi hàm này)."""
    try:
        p = pending_path(warehouse_root)
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_drift(warehouse_root: Path, ticker: str, info: dict,
                 today: "date | None" = None) -> None:
    """Ghi mã vào sổ cách ly (nguyên tử). Lỗi ghi KHÔNG được làm hỏng lượt sync."""
    try:
      with _WRITE_LOCK:
        p = pending_path(warehouse_root)
        data = load_pending(warehouse_root)
        data[ticker.upper()] = {
            "detected_at": (today or date.today()).isoformat(),
            "ratio": round(float(info.get("ratio", 0.0)), 6),
            "pct": round(float(info.get("pct", 0.0)), 4),
            "n_bars": int(info.get("n", 0)),
            "window": [info.get("first"), info.get("last")],
            "event": info.get("event"),
            "fix": (f"python scripts/rebase_ticker_history.py "
                    f"--ticker {ticker.upper()} --apply"),
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def clear_drift(warehouse_root: Path, ticker: str) -> None:
    """Bỏ mã khỏi sổ khi đã chữa. Cùng đường ghi nguyên tử."""
    try:
      with _WRITE_LOCK:
        data = load_pending(warehouse_root)
        if data.pop(ticker.upper(), None) is None:
            return
        p = pending_path(warehouse_root)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def fetch_start(last_date: date, lookback_days: int = LOOKBACK_DAYS) -> date:
    """Trần lùi tối đa — dùng để ĐỌC KHO, không phải để gọi mạng."""
    return last_date - timedelta(days=lookback_days)


# Cửa sổ chồng lấn chỉ cần đủ `MIN_BARS` bar để so trung vị. Thêm biên cho
# ngày nghỉ / mã nghỉ giao dịch, nhưng KHÔNG cần tới 30 ngày.
WANT_BARS = MIN_BARS + 3
MIN_LOOKBACK_DAYS = 3


def window_start(wh_dates, fetch_from: date,
                 want_bars: int = WANT_BARS,
                 max_days: int = LOOKBACK_DAYS,
                 min_days: int = MIN_LOOKBACK_DAYS) -> date:
    """Ngày `start` HẸP NHẤT vẫn đủ ``want_bars`` bar kho để đối chiếu.

    HÀM THUẦN. Vì sao cần: bản V1 nới thẳng 30 ngày cho MỌI mã, MỌI đêm —
    trong khi lượt cập nhật thường chỉ lấy 1-3 ngày. Tức cửa sổ fetch phình
    ~16× trên ~1.600 mã, mỗi đêm. Đo 24/08: `updater` chiếm **5.659s = 57%
    cả phát**, và cả phát 166,3' chỉ còn 13,7' đệm dưới trần task 3 giờ.

    Kho nằm ở ĐĨA (miễn phí), nên đếm bar tại chỗ rồi mới quyết nới bao nhiêu:
    mã thanh khoản cao ⇒ ~10 ngày là đủ 8 bar · mã nghỉ giao dịch dài ⇒ tự
    giãn tới trần 30 ngày. Sức phát hiện KHÔNG đổi (vẫn ≥ `MIN_BARS` bar),
    chỉ bỏ phần chồng lấn thừa.

    Không có bar nào trong kho ⇒ trả trần: chưa biết gì thì đừng thu hẹp.
    """
    floor = fetch_from - timedelta(days=max_days)
    ceil_ = fetch_from - timedelta(days=min_days)
    usable = sorted(d for d in (wh_dates or ()) if d is not None and d <= fetch_from)
    if len(usable) < want_bars:
        return floor
    start = usable[-want_bars]
    if start < floor:
        return floor
    return min(start, ceil_)


def warn_line(ticker: str, info: dict) -> str:
    ev = info.get("event")
    return (f"  ⛔ {ticker}: NGUỒN ĐÃ ĐỔI CƠ SỞ "
            f"(kho/nguồn {info.get('ratio', 0):.4f}× trên {info.get('n', 0)} bar "
            f"{info.get('first')}→{info.get('last')})"
            + (f" · sự kiện quyền: {ev}" if ev else " · không tra ra sự kiện quyền")
            + " — BỎ QUA lần nối này để không sinh bậc giả, mã đã vào sổ cách ly")
