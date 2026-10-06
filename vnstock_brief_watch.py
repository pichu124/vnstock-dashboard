"""vnstock_brief_watch.py — sổ theo dõi các NGHI NGỜ của brief, chưa đủ để vá.

Sinh ra từ đợt soi brief close 21/08/2026 (mục U22). Hai chỗ đáng ngờ nhưng
**không đủ chứng cứ để viết guard ngay**:

* **Op.CF quá lớn so với quy mô** — "KBC Op.CF=-17.344 tỷ" nhìn như lỗi đơn
  vị. Nhưng ngưỡng nào là "quá lớn" thì chưa biết: đo thô ~0,8× vốn hoá, mà
  doanh nghiệp BĐS tích luỹ quỹ đất ÂM nặng là chuyện thật — chính là tín
  hiệu mục Rủi ro sinh ra để nói. Ngưỡng đặt bừa sẽ giết đúng tín hiệu đó.
* **Câu viện dẫn dòng tiền ngoại KHÔNG có trong data** — lý do bán SSI nói
  "khối ngoại bán ròng mạnh nhóm Chứng khoán", trong khi mục Dòng Tiền của
  CÙNG brief liệt kê bên bán ròng mạnh nhất là Họ VIN và Ngân hàng.

Doctrine của repo với loại này là **ĐẾM TRƯỚC, QUYẾT SAU** (`_ACCURACY_MIN_
SAMPLE`, `_LATENCY_MIN_SAMPLES`, `cumulative_stats`). Ghi vào
`docs/CLAUDE-NOTES.md` thì KHÔNG bao giờ nổi lên lại — file đó tự nhận là kho
lưu. Nên ghi vào KHO: mỗi phiên brief tự nhặt bằng chứng, `run.py doctor` réo
khi đủ mẫu, và quyết định dựa trên số chứ không dựa trên việc ai đó có nhớ
soi brief hay không.

**Đây là SỔ THEO DÕI, không phải kế toán** — mất một quan sát vì tranh ghi
giữa hai tiến trình là chấp nhận được, không đáng khoá liên tiến trình.
"""

from __future__ import annotations

import os
import socket
import threading
from datetime import date as _date
from pathlib import Path

FILE_NAME = "brief_watch.json"
_ENV_FLAG = "VNSTOCK_BRIEF_WATCH"

# Trần sổ. Đủ dài để nhìn ra xu hướng nhiều tuần, đủ ngắn để file không phình
# trong Dropbox (kho đồng bộ giữa hai máy).
MAX_EVENTS = 400

# Sàn mẫu — DƯỚI sàn này badge TUYỆT ĐỐI không được warn, chỉ in "n=…".
# Vết 13/08 của repo: n=2 được vẽ thành "0%", tức trình bày "chưa đo được"
# thành "đo ra kết quả xấu".
MIN_SAMPLES = 5

# |Op.CF| / vốn hoá vượt mức này thì GHI LẠI (chỉ ghi, không phán).
OCF_SCALE_NOTE = 0.5

_LOCK = threading.Lock()


def enabled() -> bool:
    """Kill-switch: VNSTOCK_BRIEF_WATCH=0 để tắt hẳn việc ghi sổ."""
    return os.environ.get(_ENV_FLAG, "1").strip().lower() not in ("0", "false", "no")


def watch_path(warehouse_root) -> Path:
    return Path(warehouse_root) / "_meta" / FILE_NAME


# ─────────────────────────────────────────────────────────────────────────
# Bộ dò — HÀM THUẦN, không I/O, test được không cần kho
# ─────────────────────────────────────────────────────────────────────────
def _mcap_map(ctx: dict | None) -> dict:
    """{MÃ: vốn hoá (tỷ)} — cùng đơn vị tỷ VND với `ocf`."""
    out: dict = {}
    for row in (ctx or {}).get("tickers") or []:
        tk = str(row.get("Mã") or "").strip().upper()
        v = row.get("Vốn hoá (tỷ)")
        if tk and isinstance(v, (int, float)) and v == v and v > 0:
            out[tk] = float(v)
    return out


def _excluded_financials(ctx: dict | None) -> set:
    """Nhóm TÀI CHÍNH — dùng CHUNG danh sách với xếp hạng rủi ro của brief.

    ⚠️ Đây là chỗ sổ theo dõi từng đếm nhầm suốt 6 phiên. Đo 07/09: 83 mã bị
    ghi, đậm nhất **NAB 6.118×**, và danh sách đầu bảng là **BID · BSI · DSE ·
    HDB · NAB** — năm trên sáu mã là NGÂN HÀNG / CHỨNG KHOÁN.

    Với định chế tài chính, "lưu chuyển tiền HĐKD" theo VAS gồm cả biến động
    **tiền gửi, cho vay, liên ngân hàng** — tức dòng BẢNG CÂN ĐỐI, không phải
    dòng tiền hoạt động theo nghĩa doanh nghiệp thường. Op.CF vài chục tới vài
    trăm nghìn tỷ ở đó là **số THẬT**, không phải lệch đơn vị. `vnstock_brief_
    canon._FINANCIAL_TICKERS` đã ghi đúng điều này và xếp hạng rủi ro của
    brief ĐÃ loại nhóm đó ra ("MBB Op.CF -64,972 tỷ").

    Nên sổ đang đếm những mã **không bao giờ tới được mục Rủi ro** — đếm mãi
    cũng không ra quyết định nào. Dùng CHUNG một danh sách với xếp hạng là bất
    biến duy nhất giữ hai bên khỏi lệch nhau.

    Lấy cả `ctx["financial_tickers"]` (phân loại theo NGÀNH, bắt được mã ngoài
    danh sách tĩnh — vd DSE) như `_vn30_fund_block` và guard mục Rủi ro.
    """
    fin = {str(t).upper() for t in ((ctx or {}).get("financial_tickers") or ())}
    try:
        from vnstock_brief_canon import _FINANCIAL_TICKERS
        fin |= {str(t).upper() for t in _FINANCIAL_TICKERS}
    except Exception:
        pass
    return fin


def scan_ocf_scale(ctx: dict | None, threshold: float = OCF_SCALE_NOTE) -> list:
    """Mã có |Op.CF| lớn bất thường so với vốn hoá — GHI NHẬN, không kết tội.

    Cả hai vế đã ở đơn vị **tỷ VND** (`operating_cf` chia 1e9 lúc ghi parquet;
    `Vốn hoá (tỷ)` chia 1e9 ở runner) nên tỉ số là số không thứ nguyên.
    Thiếu vốn hoá ⇒ BỎ QUA mã đó, không đoán mẫu số.

    **Bỏ qua nhóm TÀI CHÍNH** — xem `_excluded_financials`. Ở đó tỉ số lớn là
    cấu trúc của ngành, không phải dấu hiệu sai số.
    """
    mcap = _mcap_map(ctx)
    skip = _excluded_financials(ctx)
    out = []
    for tk, m in ((ctx or {}).get("vn30_fundamentals") or {}).items():
        ocf = (m or {}).get("ocf")
        cap = mcap.get(str(tk).upper())
        if str(tk).upper() in skip:
            continue
        if not isinstance(ocf, (int, float)) or ocf != ocf or not cap:
            continue
        ratio = abs(float(ocf)) / cap
        if ratio >= threshold:
            out.append({"kind": "ocf_scale", "ticker": str(tk).upper(),
                        "ocf_ty": round(float(ocf), 1), "mcap_ty": round(cap, 0),
                        "ratio": round(ratio, 3)})
    return sorted(out, key=lambda d: -d["ratio"])


def _sector_nn(ctx: dict | None) -> dict:
    """{tên ngành đã chuẩn hoá: NN 1T (tỷ)} — bảng ĐẦY ĐỦ, không phải top-3."""
    out: dict = {}
    for row in (ctx or {}).get("sectors") or []:
        name = str(row.get("Ngành") or "").strip()
        v = row.get("NN 1T (tỷ)")
        if name and isinstance(v, (int, float)) and v == v:
            out[name.casefold()] = float(v)
    return out


def scan_flow_claims(text: str, ctx: dict | None) -> list:
    """Câu nói "khối ngoại mua/bán ròng nhóm X" mà ctx nói ngược lại.

    Guard được BIẾT NHIỀU HƠN model: prompt chỉ đưa top-3 mỗi chiều
    (`_sector_flow_block`), còn ctx giữ trọn ~32 dòng ngành. Nên "ngành bị
    gọi là bán ròng mạnh nhưng NN 1T của nó ≥ 0" là phán quyết sạch.

    CHỈ ghi nhận khi tên ngành khớp CHÍNH XÁC một dòng trong ctx — khớp mờ là
    tự tạo báo động giả. Hàm thuần, không sửa text.
    """
    import re as _re

    nn = _sector_nn(ctx)
    if not text or not nn:
        return []
    out = []
    pat = _re.compile(
        r"khối ngoại[^.\n]{0,60}?(mua ròng|bán ròng)[^.\n]{0,40}?nhóm\s+"
        r"([A-ZÀ-Ỹ][^.,;\n]{2,40})", _re.IGNORECASE)
    for m in pat.finditer(text):
        side = m.group(1).lower()
        raw = m.group(2).strip().rstrip(".,;:")
        actual = nn.get(raw.casefold())
        if actual is None:
            continue                      # không khớp được ⇒ im lặng, không đoán
        contradicted = (side == "bán ròng" and actual >= 0) or \
                       (side == "mua ròng" and actual <= 0)
        if contradicted:
            out.append({"kind": "flow_claim", "sector": raw, "claimed": side,
                        "actual_nn_1t_ty": round(actual, 1)})
    return out


# ─────────────────────────────────────────────────────────────────────────
# Đường có I/O — best-effort, KHÔNG BAO GIỜ ném
# ─────────────────────────────────────────────────────────────────────────
def scan_risk_repeat(text: str) -> list:
    """Mục '⚠️ Rủi ro cần lưu ý' của brief → 1 event 'risk_section' (dấu vân thân
    mục) để đếm "lặp y hệt phiên trước" (06/10 — khối cực trị lặp nhiều tháng
    mà không ai đếm). [] khi brief không có mục Rủi ro."""
    import hashlib

    if not text:
        return []
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith(("##", "⚠️")) and "rủi ro cần lưu ý" in l.lower()),
                 None)
    if start is None:
        return []
    try:
        from vnstock_brief_guards_common import _is_section_start
    except Exception:          # pragma: no cover — common là module lá, luôn có
        return []
    end = next((i for i in range(start + 1, len(lines)) if _is_section_start(lines[i])),
               len(lines))
    body = [l.strip() for l in lines[start + 1:end] if l.strip()]
    try:
        from vnstock_brief_canon import _RISK_LINE_PREFIXES
    except Exception:          # pragma: no cover
        _RISK_LINE_PREFIXES = ()
    codes = sorted({p for p in _RISK_LINE_PREFIXES for l in body if l.startswith(p)})
    return [{"kind": "risk_section",
             "digest": hashlib.sha1("\n".join(body).encode("utf-8")).hexdigest()[:12],
             "n_lines": len(body), "codes": codes}]


def load(warehouse_root) -> dict:
    import json
    try:
        data = json.loads(watch_path(warehouse_root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record(warehouse_root, events: list, today=None) -> bool:
    """Nối quan sát vào sổ. Trả True nếu đã ghi. Nuốt mọi lỗi."""
    if not enabled() or not events:
        return False
    stamp = str(today or _date.today())
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    try:
        from vnstock_parquet_io import write_json_atomic
        with _LOCK:
            data = load(warehouse_root)
            log = list(data.get("events") or [])
            # Cùng ngày + cùng máy thì GHI ĐÈ, không cộng dồn: chạy lại
            # `run.py brief` ba lần một tối không được thành ba lần bằng chứng.
            log = [e for e in log
                   if not (e.get("at") == stamp and e.get("host") == host)]
            for e in events:
                log.append({**e, "at": stamp, "host": host})
            data["events"] = log[-MAX_EVENTS:]
            data["total"] = int(data.get("total") or 0) + len(events)
            write_json_atomic(data, watch_path(warehouse_root))
        return True
    except Exception:
        return False


def observe_brief(warehouse_root, text: str, ctx: dict | None, today=None) -> list:
    """Nhặt hết bằng chứng của MỘT brief rồi ghi sổ. Trả danh sách đã ghi."""
    if not enabled():
        return []
    try:
        events = (scan_ocf_scale(ctx) + scan_flow_claims(text, ctx)
                  + scan_risk_repeat(text))
    except Exception:
        return []
    if events:
        record(warehouse_root, events, today=today)
    return events


def summarize(warehouse_root) -> dict:
    """Gộp sổ theo loại — cho badge doctor. Không phán, chỉ đếm."""
    events = list((load(warehouse_root) or {}).get("events") or [])
    # n_days/enough CHỈ đếm hai loại nghi ngờ cũ — event risk_section có mặt
    # mỗi phiên, cộng vào là badge cũ đổi nghĩa ("đủ mẫu" giả).
    days = {e.get("at") for e in events
            if e.get("at") and e.get("kind") in ("ocf_scale", "flow_claim")}
    ocf = [e for e in events if e.get("kind") == "ocf_scale"]
    flow = [e for e in events if e.get("kind") == "flow_claim"]
    worst = max(ocf, key=lambda e: e.get("ratio") or 0, default=None)
    # Mục Rủi ro: mỗi ngày lấy bản CUỐI; đếm cặp ngày liên tiếp (theo thứ tự
    # ngày có quan sát) và số cặp trùng dấu vân.
    risk_by_day: dict = {}
    for e in events:
        if e.get("kind") == "risk_section" and e.get("at"):
            risk_by_day[e["at"]] = e.get("digest")
    seq = [risk_by_day[d] for d in sorted(risk_by_day)]
    pairs = list(zip(seq, seq[1:]))
    return {
        "risk_pairs": len(pairs),
        "risk_repeats": sum(1 for a, b in pairs if a and a == b),
        "n_days": len(days),
        "n_ocf": len(ocf),
        "n_flow": len(flow),
        "ocf_tickers": sorted({e.get("ticker") for e in ocf if e.get("ticker")}),
        "flow_sectors": sorted({e.get("sector") for e in flow if e.get("sector")}),
        "worst_ocf": worst,
        "enough": len(days) >= MIN_SAMPLES,
    }
