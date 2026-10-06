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
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

_META = Path("data_warehouse/_meta")
UPCOMING_EVENTS_PATH = _META / "upcoming_events.parquet"
_COLS = ["ticker", "ex_date", "title", "category"]

# VCI company.events() noise we skip (insider/major-shareholder registrations) —
# keep the block about corp actions (cổ tức/chia tách/ĐHCĐ/phát hành).
_SKIP_CATEGORIES = {"MAJOR_SHAREHOLDER_TRADING"}


def _to_date(v):
    try:
        d = pd.to_datetime(v, errors="coerce")
        return None if pd.isna(d) else d.date()
    except Exception:
        return None


def _fetch_vci_events(ticker: str) -> "pd.DataFrame | None":
    """Raw VCI company.events() — the source that exposes upcoming corp actions
    (vnstock_data.Company.events() is empty at this tier)."""
    try:
        from vnstock_auth import get_vnstock
        return get_vnstock(ticker, "VCI").company.events()
    except Exception:
        return None


def _extract_upcoming(df, ticker: str, today) -> list[dict]:
    """Keep rows whose relevant date is in the future. For corp actions use
    ex-rights date (GDKHQ); for meetings/others use start/display date. Uses the
    rich `event_title_vi` as the description."""
    if df is None or getattr(df, "empty", True):
        return []
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    out: list[dict] = []
    for _, r in df.iterrows():
        cat = str(r.get("category") or "").upper()
        if cat in _SKIP_CATEGORIES:
            continue
        ex = _to_date(r.get("exright_date"))
        if ex is not None:
            kd = ex if ex >= today else None          # GDKHQ: only if upcoming
        else:
            kd = next((d for c in ("start_date", "display_date1", "record_date")
                       if (d := _to_date(r.get(c))) is not None and d >= today), None)
        if kd is None:
            continue
        title = str(r.get("event_title_vi") or r.get("event_name_vi")
                    or r.get("event_code") or "Sự kiện")[:90]
        out.append({"ticker": ticker.upper(), "ex_date": kd.isoformat(),
                    "title": title, "category": cat})
    return out


def _default_universe() -> list[str]:
    """VN30 by default (lazy import to avoid a circular dependency)."""
    try:
        from vnstock_brief import VN30_TICKERS
        return sorted(VN30_TICKERS)
    except Exception:
        return []


# Đêm VCI ốm (22/09: 52 mã × timeout 30s = 28′ NGAY TRONG bước brief, 21/09
# cùng bão này góp phần đẩy bước brief qua trần 180′): mỗi mã lỗi liên tiếp
# là một timeout 30s vô ích. Từng ấy mã lỗi liền là VCI đang ngã, không phải
# mã xấu → dừng, giữ cache cũ (merge-safe), lượt sau thử lại rẻ.
MAX_CONSECUTIVE_FAILURES = 3

# 30/09 trưa (💻 laptop, `run.py brief --export-pack`): 18 dòng "Read timed
# out" × 30s = 9,8′ dù cửa 3-mã-lỗi-liền đã có — thư viện vnstock TỰ THỬ LẠI
# ~6 lần mỗi call nên "3 mã" = 18 timeout. Hai lưới thêm: (1) NGÂN SÁCH TƯỜNG
# cho cả lượt refresh — có mã lỗi mà đã quá budget thì dừng ngay (mã lỗi đầu
# tiên đã ~3′); (2) BACKOFF: lượt refresh trắng tay ghi marker `_meta/
# upcoming_events.backoff.json`, auto-refresh của brief (`_maybe_refresh_events`)
# bỏ qua tới hết hạn — hai lượt `--export-pack` liền không đốt 2 × 3′. Chạy tay
# `python vnstock_events.py --refresh` KHÔNG xét backoff (cố ý).
EVENTS_REFRESH_BUDGET_S = 120.0      # env VNSTOCK_EVENTS_REFRESH_BUDGET_S (0 = tắt)
EVENTS_BACKOFF_MIN = 90.0            # env VNSTOCK_EVENTS_BACKOFF_MIN (0 = tắt)
_BACKOFF_NAME = "upcoming_events.backoff.json"


def _budget_s() -> float:
    raw = (os.environ.get("VNSTOCK_EVENTS_REFRESH_BUDGET_S") or "").strip()
    try:
        return float(raw) if raw else EVENTS_REFRESH_BUDGET_S
    except ValueError:
        return EVENTS_REFRESH_BUDGET_S


def _backoff_min() -> float:
    raw = (os.environ.get("VNSTOCK_EVENTS_BACKOFF_MIN") or "").strip()
    try:
        return float(raw) if raw else EVENTS_BACKOFF_MIN
    except ValueError:
        return EVENTS_BACKOFF_MIN


def _backoff_path() -> Path:
    return _META / _BACKOFF_NAME


# ── Sổ sự kiện ĐÃ QUA (06/10) ───────────────────────────────────────────────
# Cache chỉ giữ ex_date ≥ hôm-refresh − 2 ngày, nên vài ngày sau GDKHQ không
# còn ai biết mã đó từng đổi cơ sở giá. Lệnh mở xuyên qua ngày GDKHQ (GMD BUY
# @78, thưởng 50% ngày 07/10) cần biết điều đó suốt cả cửa sổ chấm — có khi
# hàng tuần, tới lúc kho được rebase tay. Sổ chỉ nhận sự kiện bị cắt vì ĐÃ QUA;
# sự kiện tương lai biến mất sau một lần fetch thành công là bị HUỶ, không ghi.
_LEDGER_NAME = "corp_actions_ledger.json"
LEDGER_KEEP_DAYS = 400


def _ledger_path() -> Path:
    return _META / _LEDGER_NAME


def _read_ledger() -> list[dict]:
    try:
        return list(json.loads(_ledger_path().read_text(encoding="utf-8"))
                    .get("events") or [])
    except Exception:
        return []


def _record_ledger(rows) -> None:
    """Gộp sự kiện vào sổ đã-qua (khử trùng, bỏ bản quá LEDGER_KEEP_DAYS).
    Best-effort: hỏng ghi sổ không được làm hỏng lượt refresh."""
    floor = date.today() - timedelta(days=LEDGER_KEEP_DAYS)
    merged: dict = {}
    for e in [*_read_ledger(), *rows]:
        d = _to_date(e.get("ex_date"))
        tk = str(e.get("ticker") or "").strip().upper()
        if d is None or not tk or d < floor:
            continue
        title = str(e.get("title") or "")
        merged[(tk, d.isoformat(), title)] = {
            "ticker": tk, "ex_date": d.isoformat(), "title": title}
    try:
        from vnstock_parquet_io import write_json_atomic
        _META.mkdir(parents=True, exist_ok=True)
        write_json_atomic({"updated_at": datetime.now().isoformat(timespec="seconds"),
                           "events": [merged[k] for k in sorted(merged)]},
                          _ledger_path())
    except Exception:
        pass


def price_events(ticker: str, after: date, through: date) -> list[dict]:
    """Sự kiện LÀM ĐỔI giá tham chiếu của `ticker` có after < ex_date ≤ through.

    Đọc sổ đã-qua ∪ cache hiện hành (cache theo `_META` như backoff/sổ — test
    nào cũng chạy trên thư mục tạm). Bỏ sự kiện chỉ chốt danh sách dự họp
    (`vnstock_corp_ratio.adjusts_price`). Trả `[{"ticker", "ex_date": date,
    "title"}]` sắp theo ngày.
    """
    from vnstock_corp_ratio import adjusts_price

    tk = str(ticker or "").strip().upper()
    rows = list(_read_ledger())
    cache = _META / UPCOMING_EVENTS_PATH.name
    if cache.exists():
        try:
            rows += pd.read_parquet(cache).to_dict("records")
        except Exception:
            pass
    seen, out = set(), []
    for e in rows:
        d = _to_date(e.get("ex_date"))
        title = str(e.get("title") or "")
        if (str(e.get("ticker") or "").strip().upper() != tk or d is None
                or not (after < d <= through) or (d, title) in seen
                or not adjusts_price(title)):
            continue
        seen.add((d, title))
        out.append({"ticker": tk, "ex_date": d, "title": title})
    return sorted(out, key=lambda e: (e["ex_date"], e["title"]))


def in_backoff(now: "datetime | None" = None) -> "str | None":
    """Lý do đang backoff (chuỗi) nếu lượt refresh trắng tay gần đây còn hạn;
    None = được refresh. Best-effort: marker hỏng = không backoff."""
    try:
        d = json.loads(_backoff_path().read_text(encoding="utf-8"))
        until = datetime.fromisoformat(str(d.get("until")))
    except Exception:
        return None
    now = now or datetime.now()
    if now >= until:
        return None
    return (f"VCI trắng tay lúc {str(d.get('at', '?'))[11:16]} ({d.get('failed', '?')} mã lỗi) "
            f"— đợi tới {until.strftime('%H:%M')} rồi thử lại")


def _write_backoff(failed: int, now: "datetime | None" = None) -> None:
    mins = _backoff_min()
    if mins <= 0:
        return
    now = now or datetime.now()
    try:
        from vnstock_parquet_io import write_json_atomic
        write_json_atomic({"at": now.isoformat(timespec="seconds"),
                           "until": (now + timedelta(minutes=mins)).isoformat(timespec="seconds"),
                           "failed": int(failed)}, _backoff_path())
    except Exception:
        pass


def _clear_backoff() -> None:
    try:
        _backoff_path().unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def refresh_upcoming(
    tickers: list[str] | None = None,
    warehouse: str = "data_warehouse",
    *,
    keep_back_days: int = 2,
    verbose: bool = False,
    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
    budget_s: "float | None" = None,
) -> pd.DataFrame:
    """Fetch corp-action events for `tickers`, keep ex_date ≥ today-keep_back,
    consolidate into one parquet. Best-effort and MERGE-SAFE: a ticker whose
    fetch FAILS (network hiccup → `_fetch_vci_events` returns None) keeps its
    previously-cached events instead of being dropped — observed an ACB dividend
    vanishing between two same-day runs when a re-fetch hiccupped and overwrote
    the good cache. Only a SUCCESSFUL fetch replaces a ticker's rows (so a
    cancelled event still clears). Returns the saved DataFrame (may be empty).
    """
    tickers = tickers or _default_universe()
    cutoff = date.today() - timedelta(days=keep_back_days)

    # Prior cache keyed by ticker, so a failed re-fetch keeps known events.
    prior: dict[str, list[dict]] = {}
    if UPCOMING_EVENTS_PATH.exists():
        try:
            pdf = pd.read_parquet(UPCOMING_EVENTS_PATH)
            for _, r in pdf.iterrows():
                prior.setdefault(str(r["ticker"]).upper(), []).append(
                    {c: r.get(c) for c in _COLS})
        except Exception:
            prior = {}

    by_ticker: dict[str, list[dict]] = dict(prior)
    refreshed = failed = streak = 0
    tickers = list(tickers)
    if budget_s is None:
        budget_s = _budget_s()
    t_start = time.monotonic()
    for i, t in enumerate(tickers):
        key = str(t).upper()
        df = _fetch_vci_events(t)
        if df is None:                       # fetch failed → keep prior rows
            failed += 1
            streak += 1
            if verbose:
                print(f"  [{t}] fetch lỗi — giữ {len(prior.get(key, []))} sự kiện cũ")
            elapsed = time.monotonic() - t_start
            if budget_s and elapsed >= budget_s:
                rest = len(tickers) - i - 1
                print(f"[events] VCI lỗi và đã {elapsed:,.0f}s ≥ ngân sách {budget_s:,.0f}s "
                      f"→ dừng, giữ cache cũ cho {rest} mã còn lại (30/09: thư viện tự "
                      f"thử lại ~6 lần/mã, 3 mã = 18 timeout = 10′)")
                break
            if max_consecutive_failures and streak >= max_consecutive_failures:
                rest = len(tickers) - i - 1
                print(f"[events] VCI lỗi {streak} mã liên tiếp → dừng, giữ cache "
                      f"cũ cho {rest} mã còn lại (đêm 22/09: 52 mã × 30s = 28′)")
                break
            continue
        streak = 0
        by_ticker[key] = _extract_upcoming(df, t, cutoff)   # success (may be [])
        refreshed += 1
        if verbose:
            print(f"  [{t}] {len(by_ticker[key])} sự kiện sắp tới")

    if refreshed == 0 and failed:
        # Không lấy được gì → KHÔNG ghi đè file (mtime giữ nguyên) để lượt sau
        # còn được thử lại; ghi là "đã refresh hôm nay" giả trong khi cache
        # vẫn là hôm qua. Ghi backoff để auto-refresh của brief không thử lại
        # ngay trong vài giờ tới (mỗi lượt thử = ~3′ timeout).
        _write_backoff(failed)
        if verbose:
            print(f"  → refresh: 0 mã OK, {failed} mã lỗi — giữ nguyên file cũ")
        return _prior_frame(prior)
    _clear_backoff()

    # Sự kiện sắp bị cắt vì ĐÃ QUA → sổ đã-qua (lệnh mở còn cần biết). Chỉ lấy
    # từ `prior`: hàng mới fetch đã được lọc ≥ cutoff sẵn, còn hàng tương lai
    # biến mất sau fetch thành công là sự kiện bị huỷ.
    _record_ledger([e for evs in prior.values() for e in evs
                    if (d := _to_date(e.get("ex_date"))) is not None and d < cutoff])

    # Flatten, drop anything now past the cutoff, dedup.
    rows = [e for evs in by_ticker.values() for e in evs
            if (d := _to_date(e.get("ex_date"))) is not None and d >= cutoff]
    out = pd.DataFrame(rows, columns=_COLS)
    if not out.empty:
        out = out.drop_duplicates(subset=["ticker", "ex_date", "title"])
        _META.mkdir(parents=True, exist_ok=True)
        # Nguyên tử: guard GDKHQ trong brief đọc thẳng file này; bản cụt là brief
    # mất cảnh báo chốt quyền mà không ai biết.
    import pyarrow as _pa
    from vnstock_parquet_io import write_table_atomic
    write_table_atomic(_pa.Table.from_pandas(out, preserve_index=False),
                       UPCOMING_EVENTS_PATH)
    if verbose:
        print(f"  → refresh: {refreshed} mã OK, {failed} mã lỗi (giữ cache cũ), "
              f"tổng {len(out)} sự kiện tương lai")
    return out


def _prior_frame(prior: dict) -> pd.DataFrame:
    rows = [e for evs in prior.values() for e in evs]
    return pd.DataFrame(rows, columns=_COLS)


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
         "title": r.get("title"), "category": r.get("category")}
        for _, r in df.iterrows()
    ]




def diag(ticker: str) -> None:
    """Dump RAW calendar methods across ALL company sources so we can see real
    columns + whether any ex_date is in the future (which source exposes it)."""
    from datetime import date as _date
    from vnstock_adjust import _company_sources
    ticker = ticker.upper()
    print(f"── 🔬 Events diagnostic — {ticker} ──")
    today = _date.today()
    methods = ("events", "dividends", "dividend_history", "cash_dividend",
               "corporate_action_dividends", "calendar", "upcoming_events",
               "schedule", "corporate_actions")
    for src_name, resolve in _company_sources():
        print(f"\n=== source: {src_name} ===")
        try:
            company = resolve(ticker)
        except Exception as e:
            print(f"  resolve lỗi: {str(e)[:100]}")
            continue
        if company is None:
            print("  company = None")
            continue
        avail = [a for a in dir(company) if not a.startswith("_")
                 and any(k in a.lower()
                         for k in ("event", "divid", "calendar", "action", "schedule"))]
        print(f"  method khả dụng: {avail}")
        for method in methods:
            attr = getattr(company, method, None)
            if attr is None:
                continue
            try:
                df = attr() if callable(attr) else attr
            except Exception as e:
                print(f"  • {method}(): lỗi — {str(e)[:80]}")
                continue
            if df is None or (hasattr(df, "empty") and df.empty):
                print(f"  • {method}(): rỗng")
                continue
            print(f"  • {method}(): shape={df.shape} | cols={[str(c) for c in df.columns]}")
            for c in df.columns:
                if any(k in str(c).lower()
                       for k in ("date", "ngay", "ex", "gdkhq", "record")):
                    try:
                        d = pd.to_datetime(df[c], errors="coerce").dt.date
                        fut = d[d >= today]
                        print(f"    [{c}] max={d.max()} | TƯƠNG LAI: {len(fut)} dòng")
                    except Exception:
                        pass
            print("    " + df.head(4).to_string()[:1200].replace("\n", "\n    "))


def _check(within: int = 30) -> None:
    ev = load_upcoming(within_days=within)
    print(f"upcoming_events.parquet tồn tại: {UPCOMING_EVENTS_PATH.exists()}")
    print(f"Sự kiện {within} ngày tới: {len(ev)}")
    for e in ev[:20]:
        print(f"  {e['ex_date']}  {e['ticker']:<6} {e.get('title')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Lịch sự kiện DN sắp tới (GDKHQ)")
    ap.add_argument("--tickers", nargs="+", help="Chỉ refresh các mã này")
    ap.add_argument("--within", type=int, default=30, help="Cửa sổ ngày cho --check")
    ap.add_argument("--check", action="store_true", help="Xem sự kiện đã cache")
    ap.add_argument("--diag", metavar="TICKER", help="In raw output các method lịch sự kiện cho 1 mã")
    args = ap.parse_args()
    if args.diag:
        diag(args.diag)
    elif args.check:
        _check(args.within)
    else:
        saved = refresh_upcoming(tickers=args.tickers, verbose=True)
        print(f"✅ Đã lưu {len(saved)} sự kiện tương lai → {UPCOMING_EVENTS_PATH}")
