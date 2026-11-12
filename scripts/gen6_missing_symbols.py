"""Mã ĐANG GIAO DỊCH mà lượt cập nhật giá thế hệ 6 bỏ sót — và nguồn nào còn trả được giá cho chúng.

Chỉ ĐỌC kho, không ghi gì vào kho. Dùng sau khi `run_daily.log` in `⏱ TỔNG` (12/11: DNSE báo
"invalid symbol" cho 205 mã mà nguồn cũ vẫn trả; vnstock 6 KHÔNG sang nguồn sau khi gặp lỗi đầu vào,
nên mã đó đứng yên). Với mỗi mã có bar gần đây nhưng thiếu phiên mới nhất (trừ mã trong sổ cách ly),
thử TỪNG nguồn đã khai trong `VNSTOCK_SOURCE` riêng rẽ — mã nào nguồn sau trả được giá là mã đáng vá.

    python scripts/gen6_missing_symbols.py              # tối đa 40 mã
    python scripts/gen6_missing_symbols.py --limit 0    # không gọi nguồn, chỉ đếm từ kho
    python scripts/gen6_missing_symbols.py --tickers AGE,AMD,BBC,BCG   # thử đúng các mã này

Đo 🖥️ 12/11: mã "thiếu phiên mới nhất" phần lớn là mã ÍT THANH KHOẢN không khớp lệnh phiên đó —
nguồn trả bar cuối TRÙNG ngày cuối của kho ⇒ cột kết luận ghi "không khớp phiên mới nhất" (không lỗi).

Kết quả in ra + `gen6_missing_report.txt` (gốc repo, đã gitignore) để dán cho Claude.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402


def classify(last_dates: dict, pending: "set[str]", recent_days: int = 10) -> dict:
    """Hàm THUẦN. `last_dates` {mã: ngày bar cuối}. Phiên mới nhất của kho = ngày lớn nhất.
    Trả {session, recent: mã có bar trong `recent_days` ngày mà thiếu phiên mới nhất (đang giao dịch
    ⇒ bị bỏ sót), old: mã đứng lâu hơn (nhiều khả năng ngừng giao dịch), quarantined: mã trong sổ}."""
    dates = [d for d in last_dates.values() if d is not None]
    if not dates:
        return {"session": None, "recent": [], "old": [], "quarantined": []}
    session = max(dates)
    floor = session - timedelta(days=recent_days)
    recent, old, quar = [], [], []
    for tk, d in sorted(last_dates.items()):
        if d is None or d >= session:
            continue
        if tk in pending:
            quar.append(tk)
        elif d >= floor:
            recent.append(tk)
        else:
            old.append(tk)
    return {"session": session, "recent": recent, "old": old, "quarantined": quar}


def _last_date(tdir: Path) -> "date | None":
    years = sorted(tdir.glob("year=*"))
    for ydir in reversed(years):                       # năm mới nhất có dữ liệu
        best = None
        for pq in ydir.glob("*.parquet"):              # có thể >1 file (conflicted copy)
            try:
                t = pd.to_datetime(pd.read_parquet(pq, columns=["time"])["time"]).dt.date
            except Exception:
                continue
            if len(t):
                best = max(best, t.max()) if best else t.max()
        if best:
            return best
    return None


def verdict(wh_last: "date | None", session: "date | None", src_last: dict) -> str:
    """Hàm THUẦN. `src_last` {nguồn: ngày bar cuối nguồn trả (None = lỗi/rỗng)}. Kết luận một mã."""
    got = [d for d in src_last.values() if d is not None]
    if not got:
        return "KHÔNG nguồn nào có mã này (ngừng giao dịch / nguồn không hỗ trợ)"
    best = max(got)
    if session is not None and best >= session:
        return "nguồn CÓ phiên mới nhất mà kho thiếu ⇒ BỊ BỎ SÓT"
    if wh_last is not None and best <= wh_last:
        return "không khớp phiên mới nhất (nguồn cũng dừng cùng ngày) — bình thường"
    return f"nguồn có bar mới hơn kho (tới {best}) ⇒ BỊ BỎ SÓT"


def _try_source(src: str, tk: str, d0: date, d1: date) -> "tuple[str, date | None]":
    import vnstock

    from vnstock_updater import _fetch_prices
    vnstock.sources.use(src)                           # CHỈ nguồn này, trong tiến trình này
    try:
        df = _fetch_prices(tk, d0.isoformat(), d1.isoformat())
    except Exception as e:  # noqa: BLE001 — công cụ đo: lỗi là kết quả
        return f"{type(e).__name__} {getattr(e, 'code', '') or ''}".strip(), None
    if df is None or df.empty:
        return "rỗng", None
    last = df.sort_values("time").iloc[-1]
    return f"{len(df)} bar, cuối {last['time']} close {float(last['close']):,.2f}", last["time"]


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--warehouse", default=str(REPO / "data_warehouse"))
    ap.add_argument("--limit", type=int, default=40, help="số mã gọi nguồn (0 = chỉ đếm)")
    ap.add_argument("--recent-days", type=int, default=10)
    ap.add_argument("--tickers", default="", help="thử đúng các mã này (phẩy ngăn cách) thay cho danh sách tự tìm")
    args = ap.parse_args(argv)
    wh = Path(args.warehouse)
    lines: list[str] = []

    def add(s: str = "") -> None:
        print(s)
        lines.append(s)

    from vnstock_basis_guard import load_pending
    pending = set(load_pending(wh))
    last = {p.name.split("=", 1)[1]: _last_date(p) for p in sorted((wh / "prices").glob("ticker=*"))}
    c = classify(last, pending, args.recent_days)
    add(f"Kho: {len(last)} mã · phiên mới nhất {c['session']}")
    add(f"  thiếu phiên mới nhất, có bar trong {args.recent_days} ngày (ít thanh khoản hoặc bị bỏ sót): {len(c['recent'])}")
    add(f"  đứng lâu hơn (nhiều khả năng ngừng giao dịch): {len(c['old'])}")
    add(f"  trong sổ cách ly lệch cơ sở: {len(c['quarantined'])}")
    add("  các mã đó: " + ", ".join(f"{t}({last[t]})" for t in c["recent"]))
    picks = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or c["recent"]
    if args.limit and picks:
        import vnstock_auth as va
        srcs = va.configure_sources(force=True)["default"]
        va.keep_schema_warnings()
        add("")
        add(f"== Thử từng nguồn đã khai ({', '.join(srcs) or '(trống)'}) cho {min(args.limit, len(picks))} mã ==")
        d1 = c["session"]
        d0 = d1 - timedelta(days=14)
        ok = {s: 0 for s in srcs}
        tally: dict = {}
        for tk in picks[: args.limit]:
            res = {s: _try_source(s, tk, d0, d1) for s in srcs}
            for s, (_, d) in res.items():
                ok[s] += d is not None
            v = verdict(last.get(tk), c["session"], {s: d for s, (_, d) in res.items()})
            tally[v] = tally.get(v, 0) + 1
            add(f"  {tk:<6} kho cuối {last.get(tk)} · " + " · ".join(f"{s}: {r}" for s, (r, _) in res.items())
                + f"\n         ⇒ {v}")
        add("  tổng trả được giá: " + ", ".join(f"{s} {n}" for s, n in ok.items()))
        for v, n in sorted(tally.items(), key=lambda kv: -kv[1]):
            add(f"  {n:>3} mã: {v}")
    out = REPO / "gen6_missing_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ Đã lưu {out} — dán nội dung này cho Claude.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
