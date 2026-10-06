"""Sổ KỲ BCTC của số cơ bản (D/E, Op.CF) — pha 2 của câu 1 = b (U75, 06/10).

Vì sao: khối cực trị "Đòn bẩy cao nhất VTZ/VJC/PET · Op.CF thấp nhất KBC/NVL"
đã RỜI brief ngày (chế độ risk_today) vì số năm đứng yên cả năm mà vẫn in mỗi
tối. User chốt (06/10): in lại bảng CHỈ khi có KỲ BCTC MỚI, kèm "kỳ trước".

Hai sổ, cả hai nằm trong kho `_meta/` (Dropbox ⇒ hai máy dùng chung):

- `fundamentals_periods.json` — CHỈ updater cơ bản ghi (cuối `update()`).
  Mỗi mã × chỉ số giữ kỳ hiện tại + giá trị + `first_seen` (ngày updater thấy
  kỳ mới) + `prev` (kỳ trước & giá trị). Lần đầu thấy một mã = MỐC
  (`first_seen=None`), không phải sự kiện — nếu không, lần chạy đầu sau khi
  deploy sẽ "báo kỳ mới" cho cả nghìn mã.
- `fund_period_announced.json` — CHỈ brief CHIỀU ghi (collect_context): sự
  kiện nào đã được xét ở phiên nào. Sự kiện được xét ở ĐÚNG MỘT phiên chiều;
  chạy lại cùng phiên (A/B, --export-pack, /brief-close) vẫn thấy y hệt.

Hàm ở đây THUẦN trừ các hàm read_*/write_*/record_frame; brief chỉ đưa vào ctx
những gì guard cần (`fund_period_news`), guard không đọc đĩa.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

META_DIR = Path(__file__).parent / "data_warehouse" / "_meta"
LEDGER_NAME = "fundamentals_periods.json"
ANNOUNCED_NAME = "fund_period_announced.json"

# (khoá trong sổ/ctx, cột giá trị trong fundamentals.parquet, cột kỳ)
METRICS = (("de", "debt_to_equity", "de_period"),
           ("ocf", "operating_cf", "ocf_period"))

# Sự kiện chưa được phiên chiều nào xét mà đã quá tuổi này (brief tắt, máy
# nghỉ dài…) thì bỏ — báo "kỳ mới" sau 1,5 tháng là tin cũ.
MAX_EVENT_AGE_DAYS = 45
# Sổ đã báo giữ bao lâu (khoá chỉ sinh khi có kỳ mới ⇒ rất thưa).
ANNOUNCED_KEEP_DAYS = 400

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


# ── Nhãn kỳ ─────────────────────────────────────────────────────────────────
# Ba dạng chuẩn: "2025" (năm) · "2026-Q2" (quý) · "2026-LK3" (lũy kế 3 quý
# đầu năm — Op.CF khi nguồn chưa có dòng năm thuần). LK4 = cả năm ⇒ "2026".

def norm_period(v) -> "str | None":
    """Chuẩn hoá nhãn kỳ về một trong ba dạng trên; không có năm ⇒ None."""
    if v is None:
        return None
    s = str(v).strip()
    m = _YEAR_RE.search(s)
    if not m:
        return None
    y = m.group()
    lk = re.fullmatch(rf"{y}-LK([1-4])", s)
    if lk:
        return y if lk.group(1) == "4" else f"{y}-LK{lk.group(1)}"
    q = re.search(r"Q\s*([1-4])", s, re.IGNORECASE)
    return f"{y}-Q{q.group(1)}" if q else y


def period_key(label: "str | None") -> tuple:
    """Khoá so sánh: năm Y > lũy kế Y > quý Y cùng số quý; năm sau > năm trước."""
    lab = norm_period(label)
    if lab is None:
        return (0, 0, 0)
    y = int(lab[:4])
    if lab.endswith(tuple(f"-LK{i}" for i in range(1, 4))):
        return (y, int(lab[-1]), 1)
    if "-Q" in lab:
        return (y, int(lab[-1]), 0)
    return (y, 4, 2)


def period_text(label: "str | None") -> str:
    """Nhãn hiển thị: 'năm 2025' · 'Q2/2026' · 'lũy kế 3 quý 2026'."""
    lab = norm_period(label)
    if lab is None:
        return ""
    y = lab[:4]
    if "-LK" in lab:
        return f"lũy kế {lab[-1]} quý {y}"
    if "-Q" in lab:
        return f"Q{lab[-1]}/{y}"
    return f"năm {y}"


def row_period_label(row) -> "str | None":
    """Nhãn kỳ của MỘT hàng báo cáo (pandas Series). VCI để kỳ ở `report_period`
    ("2025", "2026-Q1"); dạng cũ tách năm/quý (`yearReport`/`lengthReport`,
    quý 5 = năm). Không đọc được ⇒ None (mã đó không sinh sự kiện)."""
    if row is None:
        return None
    try:
        idx = list(row.index)
    except Exception:
        return None

    def _name(c) -> str:
        return (" ".join(str(x) for x in c) if isinstance(c, tuple) else str(c)).lower()

    def _val(c):
        try:
            v = row[c]
        except Exception:
            return None
        return None if v is None or (isinstance(v, float) and v != v) else v

    for c in idx:
        if "report_period" in _name(c) and _val(c) is not None:
            return norm_period(_val(c))
    year = next((_val(c) for c in idx
                 if any(k in _name(c) for k in ("yearreport", "year", "năm"))
                 and _val(c) is not None), None)
    if year is None:
        return None
    y = norm_period(year)
    if y is None:
        return None
    quarter = next((_val(c) for c in idx
                    if any(k in _name(c) for k in ("lengthreport", "quarter", "quý"))
                    and _val(c) is not None), None)
    try:
        qn = int(float(quarter)) if quarter is not None else None
    except (TypeError, ValueError):
        qn = None
    return f"{y[:4]}-Q{qn}" if qn in (1, 2, 3, 4) else y[:4]


# ── Sổ kỳ (updater ghi) ─────────────────────────────────────────────────────

def _num(v) -> "float | None":
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def fold(ledger: "dict | None", rows, today: str) -> dict:
    """Gấp các hàng fundamentals (dict có ticker + cột giá trị + cột kỳ) vào sổ.
    Trả sổ MỚI (không sửa `ledger`). Luật mỗi mã × chỉ số:
      chưa có  → MỐC (first_seen=None, prev=None);
      kỳ MỚI hơn → sự kiện: prev = kỳ cũ, first_seen = today;
      cùng kỳ, số khác (nguồn sửa) → cập nhật số, giữ first_seen/prev;
      kỳ CŨ hơn (nguồn trả nhầm hàng) → bỏ qua, giữ kỳ mới nhất."""
    tickers = {t: dict(v) for t, v in ((ledger or {}).get("tickers") or {}).items()}
    for r in rows or []:
        t = str((r or {}).get("ticker") or "").strip().upper()
        if not t:
            continue
        for key, vcol, pcol in METRICS:
            label, val = norm_period(r.get(pcol)), _num(r.get(vcol))
            if label is None or val is None:
                continue
            ent = tickers.setdefault(t, {})
            cur = ent.get(key)
            if not cur:
                ent[key] = {"period": label, "value": val,
                            "first_seen": None, "prev": None}
            elif period_key(label) > period_key(cur.get("period")):
                ent[key] = {"period": label, "value": val, "first_seen": today,
                            "prev": {"period": cur.get("period"),
                                     "value": cur.get("value")}}
            elif label == cur.get("period") and val != cur.get("value"):
                ent[key] = {**cur, "value": val}
    return {"version": 1, "updated_at": today,
            "tickers": {t: v for t, v in tickers.items() if v}}


def _read_json(path: Path) -> dict:
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_ledger(path: "Path | str | None" = None) -> dict:
    return _read_json(Path(path) if path else META_DIR / LEDGER_NAME)


def record_frame(df, path: "Path | str", today: "str | None" = None) -> int:
    """Gấp DataFrame fundamentals vào sổ ở `path` (nguyên tử). Trả số sự kiện
    kỳ mới VỪA sinh. Gọi từ updater, best-effort ở chỗ gọi."""
    from vnstock_parquet_io import write_json_atomic
    path = Path(path)
    today = today or date.today().isoformat()
    old = read_ledger(path)
    cols = ["ticker"] + [c for _, vcol, pcol in METRICS for c in (vcol, pcol)]
    rows = [{c: r.get(c) for c in cols} for r in df.to_dict("records")]
    new = fold(old, rows, today)
    write_json_atomic(new, path)
    old_t = old.get("tickers") or {}
    return sum(1 for t, ent in new["tickers"].items() for k, m in ent.items()
               if m.get("first_seen") == today
               and ((old_t.get(t) or {}).get(k) or {}).get("period") != m.get("period"))


# ── Sự kiện cho brief (brief đọc; brief CHIỀU ghi sổ đã báo) ────────────────

def event_key(ticker: str, metric: str, period: str) -> str:
    return f"{ticker}|{metric}|{period}"


def period_news(ledger: dict, announced: dict, tickers, data_date: str,
                max_age_days: int = MAX_EVENT_AGE_DAYS) -> dict:
    """Sự kiện kỳ mới CÒN được xét ở phiên `data_date`, cho các mã `tickers`.

    Được xét khi: có first_seen (không phải mốc), chưa quá tuổi, và CHƯA phiên
    chiều nào xét HOẶC phiên đã xét chính là `data_date` (chạy lại cùng phiên
    ra y hệt). Trả {mã: {chỉ số: {period, prev_period, prev_value, first_seen}}}."""
    try:
        d0 = date.fromisoformat(str(data_date)[:10])
    except ValueError:
        return {}
    want = {str(t).upper() for t in (tickers or ())}
    out: dict = {}
    for t, ent in ((ledger or {}).get("tickers") or {}).items():
        if t not in want:
            continue
        for key, _, _ in METRICS:
            m = (ent or {}).get(key) or {}
            prev = m.get("prev") or {}
            if not m.get("first_seen") or not prev.get("period"):
                continue
            try:
                age = (d0 - date.fromisoformat(str(m["first_seen"])[:10])).days
            except ValueError:
                continue
            if age > max_age_days:
                continue
            seen = (announced or {}).get(event_key(t, key, m.get("period")))
            if seen and seen != str(data_date)[:10]:
                continue
            out.setdefault(t, {})[key] = {
                "period": m.get("period"), "first_seen": m.get("first_seen"),
                "prev_period": prev.get("period"), "prev_value": _num(prev.get("value"))}
    return out


def mark_announced(announced: "dict | None", news: dict, data_date: str) -> dict:
    """Sổ đã báo MỚI: thêm khoá cho mọi sự kiện trong `news` (giữ ngày cũ nếu đã
    có) và bỏ khoá quá ANNOUNCED_KEEP_DAYS. Không sửa `announced`."""
    d = str(data_date)[:10]
    out = dict(announced or {})
    for t, metrics in (news or {}).items():
        for key, ev in metrics.items():
            out.setdefault(event_key(t, key, ev.get("period")), d)
    try:
        d0 = date.fromisoformat(d)
    except ValueError:
        return out
    keep = {}
    for k, v in out.items():
        try:
            if (d0 - date.fromisoformat(str(v)[:10])).days <= ANNOUNCED_KEEP_DAYS:
                keep[k] = v
        except ValueError:
            continue
    return keep


def read_announced(path: "Path | str | None" = None) -> dict:
    data = _read_json(Path(path) if path else META_DIR / ANNOUNCED_NAME)
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def write_announced(announced: dict, path: "Path | str | None" = None) -> None:
    from vnstock_parquet_io import write_json_atomic
    write_json_atomic(announced, Path(path) if path else META_DIR / ANNOUNCED_NAME)


# ── CLI soi sổ: python vnstock_fund_periods.py ──────────────────────────────

def summary(ledger: dict, announced: dict, today: "str | None" = None) -> list:
    """Các dòng tóm tắt sổ (hàm thuần): số mã, phân bố kỳ theo chỉ số, sự kiện
    kỳ mới còn trong cửa sổ 45 ngày và trạng thái đã báo."""
    from collections import Counter
    tickers = (ledger or {}).get("tickers") or {}
    out = [f"Sổ kỳ BCTC: {len(tickers)} mã · cập nhật {ledger.get('updated_at') or '—'}"]
    if not tickers:
        return out + ["(chưa có — sổ sinh ở lượt `fundamentals` T7 đầu tiên sau khi merge)"]
    for key, _, _ in METRICS:
        cnt = Counter(m[key]["period"] for m in tickers.values() if m.get(key))
        top = " · ".join(f"{period_text(p)} ×{n}" for p, n in cnt.most_common(4))
        out.append(f"  {key}: {sum(cnt.values())} mã — {top or '—'}")
    d = today or date.today().isoformat()
    news = period_news(ledger, {}, tickers.keys(), d)
    out.append(f"Sự kiện kỳ mới trong {MAX_EVENT_AGE_DAYS} ngày: "
               f"{sum(len(v) for v in news.values())}")
    for t, metrics in sorted(news.items()):
        for key, ev in metrics.items():
            seen = (announced or {}).get(event_key(t, key, ev["period"]))
            out.append(f"  {t} {key}: {period_text(ev['prev_period'])} → "
                       f"{period_text(ev['period'])} (thấy {ev['first_seen']}; "
                       f"{'đã xét phiên ' + seen if seen else 'chưa phiên chiều nào xét'})")
    return out


if __name__ == "__main__":
    print("\n".join(summary(read_ledger(), read_announced())))
