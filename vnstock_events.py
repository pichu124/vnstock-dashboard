"""
vnstock_events.py — Lịch sự kiện doanh nghiệp sắp tới.

Tổng hợp corp-action events (GDKHQ cổ tức tiền mặt / chia tách / thưởng CP) cho
một rổ mã — tái dùng máy fetch của ``vnstock_adjust`` (Company.events() /
dividends()) — lọc các sự kiện có ``ex_date`` trong tương lai gần và cache vào
``data_warehouse/_meta/upcoming_events.parquet`` để brief nạp nhanh.

Đây là phần "sự kiện kinh tế sắp tới" KHẢ THI NGAY (không cần nguồn ngoài). Tin
vĩ mô / lịch CPI-Fed-SBV là nguồn khác, chưa tích hợp.

CLI:
  python vnstock_events.py                    # refresh VN30
  python vnstock_events.py --tickers FPT VCB  # refresh vài mã
  python vnstock_events.py --within 10 --check
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

_META = Path("data_warehouse/_meta")
UPCOMING_EVENTS_PATH = _META / "upcoming_events.parquet"
_COLS = ["ticker", "ex_date", "type", "cash_amount", "ratio"]


def _default_universe() -> list[str]:
    """VN30 by default (lazy import to avoid a circular dependency)."""
    try:
        from vnstock_brief import VN30_TICKERS
        return sorted(VN30_TICKERS)
    except Exception:
        return []


def refresh_upcoming(
    tickers: list[str] | None = None,
    warehouse: str = "data_warehouse",
    *,
    keep_back_days: int = 2,
    verbose: bool = False,
) -> pd.DataFrame:
    """Fetch corp-action events for `tickers`, keep ex_date ≥ today-keep_back,
    consolidate into one parquet. Best-effort: a single failing ticker is
    skipped. Returns the saved DataFrame (may be empty).
    """
    from vnstock_adjust import refresh_events  # fetch + per-ticker cache

    tickers = tickers or _default_universe()
    cutoff = date.today() - timedelta(days=keep_back_days)
    rows: list[dict] = []
    for t in tickers:
        try:
            df = refresh_events(t, warehouse=Path(warehouse), verbose=verbose)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            try:
                exd = pd.to_datetime(r.get("ex_date")).date()
            except Exception:
                continue
            if exd < cutoff:
                continue
            rows.append({
                "ticker": str(r.get("ticker") or t).upper(),
                "ex_date": exd.isoformat(),
                "type": str(r.get("type") or ""),
                "cash_amount": r.get("cash_amount"),
                "ratio": r.get("ratio"),
            })

    out = pd.DataFrame(rows, columns=_COLS)
    if not out.empty:
        out = out.drop_duplicates(subset=["ticker", "ex_date", "type"])
        _META.mkdir(parents=True, exist_ok=True)
        out.to_parquet(UPCOMING_EVENTS_PATH, index=False)
    return out


def load_upcoming(
    within_days: int = 14,
    tickers=None,
    path: "str | Path | None" = None,
    today: "date | None" = None,
) -> list[dict]:
    """Upcoming events with today ≤ ex_date ≤ today+within_days (optionally
    filtered to `tickers`), sorted by ex_date. [] when cache is missing."""
    p = Path(path) if path else UPCOMING_EVENTS_PATH
    if not p.exists():
        return []
    try:
        df = pd.read_parquet(p)
    except Exception:
        return []
    if df.empty or "ex_date" not in df.columns:
        return []
    t0 = today or date.today()
    t1 = t0 + timedelta(days=within_days)
    df = df.copy()
    df["_d"] = pd.to_datetime(df["ex_date"], errors="coerce").dt.date
    df = df.dropna(subset=["_d"])
    df = df[(df["_d"] >= t0) & (df["_d"] <= t1)]
    if tickers is not None:
        ts = {str(x).upper() for x in tickers}
        df = df[df["ticker"].astype(str).str.upper().isin(ts)]
    df = df.sort_values("_d")
    return [
        {"ticker": str(r["ticker"]), "ex_date": str(r["ex_date"]),
         "type": r.get("type"), "cash_amount": r.get("cash_amount"),
         "ratio": r.get("ratio")}
        for _, r in df.iterrows()
    ]


def _check(within: int = 30) -> None:
    ev = load_upcoming(within_days=within)
    print(f"upcoming_events.parquet tồn tại: {UPCOMING_EVENTS_PATH.exists()}")
    print(f"Sự kiện {within} ngày tới: {len(ev)}")
    for e in ev[:20]:
        print(f"  {e['ex_date']}  {e['ticker']:<6} {e['type']:<7} "
              f"cash={e.get('cash_amount')} ratio={e.get('ratio')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Lịch sự kiện DN sắp tới (GDKHQ)")
    ap.add_argument("--tickers", nargs="+", help="Chỉ refresh các mã này")
    ap.add_argument("--within", type=int, default=30, help="Cửa sổ ngày cho --check")
    ap.add_argument("--check", action="store_true", help="Xem sự kiện đã cache")
    args = ap.parse_args()
    if args.check:
        _check(args.within)
    else:
        saved = refresh_upcoming(tickers=args.tickers, verbose=True)
        print(f"✅ Đã lưu {len(saved)} sự kiện tương lai → {UPCOMING_EVENTS_PATH}")
