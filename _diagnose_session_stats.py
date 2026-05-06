"""Diagnostic: matched vs deal breakdown for 9/3, 10/3 + force backfill.

Run from repo root:
    python _diagnose_session_stats.py           # just print
    python _diagnose_session_stats.py --rebuild # trigger backfill first
"""
import json
import sys
from pathlib import Path

CACHE = Path("data_warehouse/_meta/market_session_stats.json")

# Optionally trigger backfill before printing — bypasses the Streamlit
# session_state guard that normally limits backfill to once per session.
if "--rebuild" in sys.argv:
    print("Triggering backfill (this may take 5-30s)...")
    from vnstock_session_stats import backfill_session_stats
    n = backfill_session_stats()
    print(f"Backfill filled {n} dates.\n")

if not CACHE.exists():
    print(f"Cache not found at {CACHE}")
    raise SystemExit

data = json.loads(CACHE.read_text(encoding="utf-8"))

dates = ["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"]
indices = ["VNINDEX", "VN30", "HNX", "UPCOM"]

print(f"\n{'='*88}")
print(f"  9h-15h session comparison: total vs matched-only vs block deal")
print(f"{'='*88}")
print(f"{'Date':<12}{'Index':<10}{'GTGD total':>14}{'GTGD matched':>16}"
      f"{'GTGD deal':>14}{'matched %':>12}{'deal %':>10}")
print("-" * 88)

any_data = False
for d in dates:
    if d not in data:
        print(f"{d:<12}  (not in cache)")
        continue
    full = data[d].get("9h-15h", {})
    for idx in indices:
        cell = full.get(idx, {})
        total = cell.get("gtgd", 0)
        matched = cell.get("gtgd_matched", 0)
        deal = cell.get("gtgd_deal", 0)
        if total == 0:
            continue
        any_data = True
        m_pct = (matched / total * 100) if total > 0 else 0
        d_pct = (deal / total * 100) if total > 0 else 0
        print(f"{d:<12}{idx:<10}{total:>14,.1f}{matched:>16,.1f}"
              f"{deal:>14,.1f}{m_pct:>11.1f}%{d_pct:>9.1f}%")
    print()

if any_data:
    # Inspect raw cell of one date to see what fields are present
    sample = data.get("2026-03-09", {}).get("9h-15h", {}).get("VNINDEX", {})
    print(f"Raw cell 2026-03-09 VNINDEX 9h-15h: {sample}")

print("""
Đọc kết quả:
  • matched/deal = 0 cho mọi cell → cache chưa được rebuild với code mới.
    Chạy: python _diagnose_session_stats.py --rebuild
  • Nếu 9/3 và 10/3 có deal % cao (≥30%) khi 11/3 chỉ ~5% → block deals lớn.
  • Nếu matched-only của 9/3 ngang 11/3 → không phải bug, là phiên có block deals.
""")
