"""📈 Net-worth curve — đường giá trị danh mục (NAV) theo thời gian, display-only.

Món DojoAgents (khảo sát 15/07, spec nâng cấp 20/07 từ `portfolio_performance.py`
+ fix của họ "dropped NAV points inflating vol/Sharpe/drawdown"):

- **NAV(t) = tiền mặt ngầm định + Σ qty×close(t)** các vị thế đã mua tính đến t.
  Vốn của vị thế CHƯA mua (buy_date > t) tính như tiền mặt 0% — mirror
  order-replay có cash của DojoAgents. Nếu bỏ hẳn vị thế chưa mua (sketch v0),
  mỗi lần mua thêm tạo bước nhảy "nạp tiền" đội lốt lợi nhuận → so VNINDEX
  thành outperform giả + vol/Sharpe bẩn.
- **Trục ngày = ngày bar VNINDEX** trong kho (lịch HOSE tự nhiên), KHÔNG phải
  "những ngày tình cờ có giá" — ngày bị drop khiến return 2-3 phiên đội lốt
  1 phiên → vol/Sharpe/maxDD phồng sai (đúng bug DojoAgents đã vá 13/07).
- **Forward-fill close từng mã** (mã thiếu bar/tạm ngừng → carry close cuối);
  chỉ bỏ ngày khi một mã đang giữ CHƯA TỪNG có bar tính đến hôm đó
  (đếm `skipped_days` để UI minh bạch).
- **Rebase cả NAV lẫn VNINDEX về 100** tại ngày đầu chung → so trực tiếp.
- **Đơn vị**: kho parquet trộn VND thô ↔ nghìn đồng per-bar (bẫy
  `_normalize_prices` đã ghi trong CLAUDE.md) → mỗi chuỗi giá được NEO về
  đơn vị `buy_price` user gõ, qua close phiên ≤ ngày mua (khớp lũy thừa 1000
  gần nhất trong dung sai; ngoài dung sai giữ nguyên, không đoán bừa).

Zero LLM / zero fetch — chỉ đọc `_meta/portfolio.json` + kho parquet.
Display-only: KHÔNG ghi DB, không đụng convention P&L/reconciler hiện có.

CLI:  python vnstock_networth.py [--warehouse DIR] [--json]
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from pathlib import Path
from typing import Optional

DEFAULT_WAREHOUSE = Path("data_warehouse")
_INDEX_TICKER = "VNINDEX"
_TRADING_DAYS_YEAR = 250      # HOSE ~250 phiên/năm
_MAX_CURVE_DAYS = 1900        # trần đọc kho (~5 năm lịch)
_ANCHOR_TOL = (0.5, 2.0)      # ratio/1000^k phải nằm trong đây mới dám rescale
_MIN_RISK_STAT_SESSIONS = 10  # dưới ngưỡng: ẩn vol/Sharpe/Calmar (nhiễu)


# ── helpers thuần ──────────────────────────────────────────────────────────

def _ffill(dates: list[str], values: list[float], day: str) -> Optional[float]:
    """Close của phiên gần nhất ≤ day (forward-fill); None khi chưa từng có bar."""
    i = bisect_right(dates, day)
    if i == 0:
        return None
    return values[i - 1]


def _anchor_factor(dates: list[str], values: list[float],
                   buy_date: str, buy_price: float) -> float:
    """Hệ số đưa chuỗi giá về ĐƠN VỊ buy_price của user (1.0 / 1000 / 0.001…).

    Neo bằng close phiên ≤ buy_date (kho bắt đầu sau ngày mua → bar đầu tiên):
    close cùng-ngày lệch buy_price tối đa ~±biên độ phiên, nên tỷ số phải khớp
    một lũy thừa 1000 trong dung sai `_ANCHOR_TOL`; ngoài dung sai giữ 1.0.
    """
    if buy_price <= 0 or not dates:
        return 1.0
    c = _ffill(dates, values, buy_date)
    if c is None:
        c = values[0]
    if not c or c <= 0:
        return 1.0
    ratio = c / buy_price
    try:
        k = round(math.log(ratio, 1000.0))
    except ValueError:
        return 1.0
    if k == 0:
        return 1.0
    residual = ratio / (1000.0 ** k)
    if _ANCHOR_TOL[0] <= residual <= _ANCHOR_TOL[1]:
        return 1000.0 ** (-k)
    return 1.0


def compute_curve_stats(navs: list[float]) -> dict:
    """Thống kê deterministic trên chuỗi NAV (mirror block risk-stats DojoAgents):
    tích lũy % · vol năm hóa √250 · Sharpe (rf=0) · maxDD % · Calmar · số phiên.
    Suy biến → None thay vì chia 0."""
    out: dict = {"cumulative_pct": None, "ann_vol_pct": None, "sharpe": None,
                 "max_drawdown_pct": None, "calmar": None, "n_days": 0}
    clean = [float(v) for v in navs
             if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]
    out["n_days"] = len(clean)
    if len(clean) < 2:
        return out
    first, last = clean[0], clean[-1]
    cum = (last / first - 1) * 100
    out["cumulative_pct"] = cum if math.isfinite(cum) else None

    rets = [b / a - 1 for a, b in zip(clean, clean[1:]) if a > 0]
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
        if sd > 0:
            vol = sd * math.sqrt(_TRADING_DAYS_YEAR) * 100
            sharpe = mean / sd * math.sqrt(_TRADING_DAYS_YEAR)
            out["ann_vol_pct"] = vol if math.isfinite(vol) else None
            out["sharpe"] = sharpe if math.isfinite(sharpe) else None
        else:
            out["ann_vol_pct"] = 0.0
    elif len(rets) == 1:
        out["ann_vol_pct"] = 0.0

    peak = clean[0]
    mdd = 0.0
    for v in clean:
        peak = max(peak, v)
        mdd = min(mdd, (v / peak - 1) * 100)
    out["max_drawdown_pct"] = mdd if math.isfinite(mdd) else None

    if mdd < 0:
        try:
            ann = ((last / first) ** (_TRADING_DAYS_YEAR / (len(clean) - 1)) - 1) * 100
            calmar = ann / abs(mdd)
            out["calmar"] = calmar if math.isfinite(calmar) else None
        except (OverflowError, ZeroDivisionError, ValueError):
            out["calmar"] = None
    return out


def _valid_positions(positions, *, today: Optional[str] = None) -> list[dict]:
    """Lọc vị thế hợp lệ: qty/buy_price > 0, buy_date dạng YYYY-MM-DD,
    KHÔNG ở tương lai (gõ nhầm ngày → bỏ, kẻo thành tiền mặt vĩnh viễn)."""
    out: list[dict] = []
    for p in positions or []:
        try:
            tk = str(p.get("ticker") or "").upper().strip()
            qty = float(p.get("quantity") or 0)
            price = float(p.get("buy_price") or 0)
            bd = str(p.get("buy_date") or "")[:10]
        except (TypeError, ValueError, AttributeError):
            continue
        if not tk or qty <= 0 or price <= 0:
            continue
        if len(bd) != 10 or bd[4] != "-" or bd[7] != "-":
            continue
        if today and bd > today:
            continue
        out.append({"ticker": tk, "quantity": qty,
                    "buy_price": price, "buy_date": bd})
    return out


# ── core thuần (tests không cần I/O) ───────────────────────────────────────

def build_networth(positions: list[dict],
                   closes_by_ticker: dict[str, list[tuple[str, float]]],
                   index_closes: list[tuple[str, float]],
                   *, today: Optional[str] = None) -> Optional[dict]:
    """Dựng curve từ data đã nạp sẵn.

    positions: [{ticker, quantity, buy_price, buy_date}] (buy_price đơn vị user).
    closes_by_ticker: {ticker: [(iso_date, close), …] TĂNG DẦN, nội bộ nhất quán}.
    index_closes: [(iso_date, close), …] VNINDEX — rỗng → trục fallback = hợp
    ngày của các mã, đường index None.

    Trả None khi không có vị thế hợp lệ / < 2 phiên vẽ được.
    """
    pos = _valid_positions(positions, today=today)
    excluded = sorted({p["ticker"] for p in pos
                       if not closes_by_ticker.get(p["ticker"])})
    pos = [p for p in pos if closes_by_ticker.get(p["ticker"])]
    if not pos:
        return None

    series: dict[str, tuple[list[str], list[float]]] = {}
    factor: dict[str, float] = {}
    for p in pos:
        tk = p["ticker"]
        if tk in series:
            continue
        pts = closes_by_ticker[tk]
        series[tk] = ([d for d, _ in pts], [c for _, c in pts])
        factor[tk] = _anchor_factor(series[tk][0], series[tk][1],
                                    p["buy_date"], p["buy_price"])

    start = min(p["buy_date"] for p in pos)
    idx_dates = [d for d, _ in index_closes or []]
    idx_vals = [c for _, c in index_closes or []]
    has_index = bool(idx_dates)
    if has_index:
        master = [d for d in idx_dates if d >= start]
    else:
        master = sorted({d for ds, _ in series.values() for d in ds if d >= start})
    if today:
        master = [d for d in master if d <= today]

    dates: list[str] = []
    navs: list[float] = []
    idx_line: list[Optional[float]] = []
    skipped = 0
    for day in master:
        cash = sum(p["quantity"] * p["buy_price"]
                   for p in pos if p["buy_date"] > day)
        value = 0.0
        missing = False
        for p in pos:
            if p["buy_date"] > day:
                continue
            ds, vs = series[p["ticker"]]
            c = _ffill(ds, vs, day)
            if c is None:          # mã đang giữ CHƯA TỪNG có bar tới hôm nay
                missing = True
                break
            value += p["quantity"] * c * factor[p["ticker"]]
        if missing:
            skipped += 1
            continue
        nav = cash + value
        if not (math.isfinite(nav) and nav > 0):
            skipped += 1
            continue
        dates.append(day)
        navs.append(nav)
        idx_line.append(_ffill(idx_dates, idx_vals, day) if has_index else None)

    if len(dates) < 2:
        return None

    def _rebase(vals: list) -> Optional[list[float]]:
        if not vals or vals[0] is None or vals[0] <= 0:
            return None
        return [v / vals[0] * 100 for v in vals]

    index_rebased = None
    if has_index and all(v is not None and v > 0 for v in idx_line):
        index_rebased = _rebase(idx_line)

    return {
        "dates": dates,
        "nav": navs,
        "nav_rebased": _rebase(navs),
        "index_rebased": index_rebased,
        "stats": compute_curve_stats(navs),
        "skipped_days": skipped,
        "excluded": excluded,
    }


def summary_parts(res: dict) -> list[str]:
    """Các mẩu caption thống kê — UI (portfolio_tab) và CLI DÙNG CHUNG
    (parity by construction, mirror _macro_body_lines).

    Chuỗi < `_MIN_RISK_STAT_SESSIONS` phiên: ẨN vol/Sharpe/Calmar — 1-2
    khoảng return là nhiễu thống kê ("Calmar −16.02" trên 2 điểm, verify
    máy user 20/07); giữ tích lũy / VNINDEX cùng kỳ / maxDD.
    """
    s = res.get("stats") or {}
    dates = res.get("dates") or []
    parts = [f"{len(dates)} phiên"]
    if s.get("cumulative_pct") is not None:
        parts.append(f"tích lũy {s['cumulative_pct']:+.1f}%")
    idx = res.get("index_rebased")
    if idx:
        parts.append(f"VNINDEX cùng kỳ {idx[-1] - 100:+.1f}%")
    if s.get("max_drawdown_pct") is not None:
        parts.append(f"maxDD {s['max_drawdown_pct']:.1f}%")
    if len(dates) >= _MIN_RISK_STAT_SESSIONS:
        if s.get("ann_vol_pct") is not None:
            parts.append(f"vol năm hóa {s['ann_vol_pct']:.1f}%")
        if s.get("sharpe") is not None:
            parts.append(f"Sharpe (rf=0) {s['sharpe']:.2f}")
        if s.get("calmar") is not None:
            parts.append(f"Calmar {s['calmar']:.2f}")
    else:
        parts.append("vol/Sharpe/Calmar hiện khi đủ "
                     f"≥{_MIN_RISK_STAT_SESSIONS} phiên")
    return parts


# ── loaders (đọc kho — CLI-safe, mirror vnstock_preset_score) ──────────────

def _span_days(start: str, today: str) -> int:
    """Số ngày lịch cần đọc kho để phủ từ `start` (ngày mua sớm nhất) tới
    `today`, +30 ngày đệm để `_anchor_factor` luôn có close ≤ ngày mua;
    kẹp [90, _MAX_CURVE_DAYS]. `start` rác/rỗng → 400 (hành vi cũ).

    DÙNG CHUNG với dashboard/portfolio_tab.resolve_current_price — cửa sổ
    cứng 400 ngày ở đó từng làm neo đơn vị trượt mốc khi buy_date già hơn
    cửa sổ (review 21/07)."""
    from datetime import date as _date
    try:
        span = (_date.fromisoformat(today) - _date.fromisoformat(start)).days + 30
    except ValueError:
        span = 400
    return max(90, min(span, _MAX_CURVE_DAYS))


def _close_series(ticker: str, days: int,
                  prices_dir: Optional[Path] = None) -> list[tuple[str, float]]:
    """[(iso_date, close), …] tăng dần, đơn vị nội bộ nhất quán (stitch) —
    đọc parquet trực tiếp qua `_load_history_from_parquet` (CLI-safe)."""
    try:
        from vnstock_strategy import _load_history_from_parquet
        from vnstock_preset_score import _stitch_units
    except Exception:
        return []
    out: list[tuple[str, float]] = []
    try:
        hist = _load_history_from_parquet(ticker, days=days, prices_dir=prices_dir)
        if hist is not None and not hist.empty and "close" in hist.columns:
            for _, row in hist.iterrows():
                try:
                    d = str(row["time"])[:10]
                    c = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if c > 0:
                    out.append((d, c))
    except Exception:
        return []
    return _stitch_units(sorted(out))


def load_networth(warehouse: Path | str = DEFAULT_WAREHOUSE) -> Optional[dict]:
    """Đọc `_meta/portfolio.json` + kho parquet → `build_networth`.
    None khi chưa có vị thế hợp lệ / chưa đủ data (UI tự caption)."""
    warehouse = Path(warehouse)
    path = warehouse / "_meta" / "portfolio.json"
    if not path.exists():
        return None
    try:
        positions = json.loads(path.read_text())
    except Exception:
        return None

    from datetime import date as _date
    today = _date.today().isoformat()
    pos = _valid_positions(positions, today=today)
    if not pos:
        return None

    start = min(p["buy_date"] for p in pos)
    days = _span_days(start, today)

    prices_dir = warehouse / "prices"
    closes = {tk: _close_series(tk, days, prices_dir=prices_dir)
              for tk in sorted({p["ticker"] for p in pos})}
    index_closes = _close_series(_INDEX_TICKER, days, prices_dir=prices_dir)
    return build_networth(pos, closes, index_closes, today=today)


# ── CLI ────────────────────────────────────────────────────────────────────

def _fmt(v: Optional[float], nd: int = 2) -> str:
    return "—" if v is None else f"{v:,.{nd}f}"


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Net-worth curve danh mục (display-only, zero fetch/LLM)")
    ap.add_argument("--warehouse", default=str(DEFAULT_WAREHOUSE),
                    help="thư mục data_warehouse")
    ap.add_argument("--json", action="store_true",
                    help="in JSON đầy đủ (dates/nav/rebase/stats)")
    args = ap.parse_args(argv)

    res = load_networth(args.warehouse)
    if res is None:
        print("Chưa có vị thế hợp lệ hoặc chưa đủ dữ liệu giá (cần ≥ 2 phiên "
              "kể từ ngày mua sớm nhất).")
        return 0
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    print(f"📈 NAV danh mục: {len(res['dates'])} phiên "
          f"{res['dates'][0]} → {res['dates'][-1]}")
    line = f"   Danh mục (rebase): {_fmt(res['nav_rebased'][-1], 1)}"
    if res.get("index_rebased"):
        line += f" · VNINDEX (rebase): {_fmt(res['index_rebased'][-1], 1)}"
    print(line)
    print("   " + " · ".join(summary_parts(res)))
    if res.get("skipped_days"):
        print(f"   ⚠️ Bỏ {res['skipped_days']} phiên thiếu giá (mã chưa có bar).")
    if res.get("excluded"):
        print(f"   ⚠️ Loại mã không có dữ liệu giá: {', '.join(res['excluded'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
