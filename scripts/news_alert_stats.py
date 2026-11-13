"""Thống kê tin mỗi giờ theo NGÀY từ sổ `_meta/news_alert_seen.json` (giữ 7 ngày, đi qua Dropbox).

Chỉ đọc, không gọi mạng, không cần vnstock — chạy được bằng venv nào cũng được, ở máy nào cũng được.
Mỗi ngày: số GIỜ có lượt chạy (giờ có tin được thấy lần đầu — máy tắt/ngủ thì giờ đó trống), tin
mới thấy, tin đã chấm, điểm cao nhất, tin ≥ ngưỡng, tin ĐÃ GỬI (+ tin bù). Kèm marker lượt cuối.

    python scripts/news_alert_stats.py
    python scripts/news_alert_stats.py --min-score 65
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def daily_stats(seen: dict, min_score: int = 75) -> "list[dict]":
    """Hàm THUẦN: gom bản ghi sổ theo ngày (`first_seen` cho tin thấy/chấm, `sent_at` cho tin gửi)."""
    days: dict = defaultdict(lambda: {"hours": set(), "seen": 0, "scored": 0, "max": None,
                                      "pass": 0, "sent": 0, "topup": 0, "sources": set()})
    for r in (seen.get("items") or {}).values():
        if not isinstance(r, dict):
            continue
        fs = str(r.get("first_seen") or "")
        if len(fs) >= 13:
            d = days[fs[:10]]
            d["hours"].add(fs[11:13])
            d["seen"] += 1
            d["sources"].add(r.get("source_key") or r.get("source") or "?")
            sc = r.get("score")
            if isinstance(sc, (int, float)):
                d["scored"] += 1
                d["max"] = sc if d["max"] is None else max(d["max"], sc)
                d["pass"] += sc >= min_score
        sa = str(r.get("sent_at") or "")
        if r.get("sent") and len(sa) >= 10:
            days[sa[:10]]["sent"] += 1
            days[sa[:10]]["topup"] += bool(r.get("topup"))
    return [{"day": k, "hours": len(v["hours"]), "seen": v["seen"], "scored": v["scored"],
             "max": v["max"], "pass": v["pass"], "sent": v["sent"], "topup": v["topup"],
             "sources": len(v["sources"])} for k, v in sorted(days.items())]


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--meta", default=str(REPO / "data_warehouse" / "_meta"))
    ap.add_argument("--min-score", type=int, default=75, help="ngưỡng để đếm cột ≥ngưỡng (mặc định 75)")
    args = ap.parse_args(argv)
    meta = Path(args.meta)
    seen = json.loads((meta / "news_alert_seen.json").read_text(encoding="utf-8"))
    print(f"{'ngày':<11} {'giờ chạy':>8} {'tin mới':>7} {'đã chấm':>7} {'max':>4} "
          f"{'≥' + str(args.min_score):>5} {'đã gửi':>6} {'(bù)':>5} {'nguồn':>5}")
    for d in daily_stats(seen, args.min_score):
        print(f"{d['day']:<11} {d['hours']:>8} {d['seen']:>7} {d['scored']:>7} "
              f"{'' if d['max'] is None else d['max']:>4} {d['pass']:>5} {d['sent']:>6} "
              f"{d['topup']:>5} {d['sources']:>5}")
    st = meta / "news_alert_status.json"
    if st.exists():
        s = json.loads(st.read_text(encoding="utf-8"))
        keys = ("machine", "ran_at", "engine", "claude_error", "fetched", "in_window", "new", "scored",
                "picked", "sent", "min_score", "min_value", "reviewed", "rejected", "review_error",
                "target_per_h", "sent_24h", "window_h", "error", "error_streak")
        print("\nmarker lượt cuối: " + " · ".join(f"{k}={s[k]}" for k in keys if k in s))
        src = s.get("sources") or {}
        empty = sorted(k for k, v in src.items() if not v)
        if src:
            print(f"nguồn lượt cuối: {len(src) - len(empty)}/{len(src)} có tin"
                  + (f" · rỗng: {', '.join(empty)}" if empty else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
