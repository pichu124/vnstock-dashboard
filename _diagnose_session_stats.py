"""Quick diagnostic: print matched vs deal breakdown for 9/3, 10/3, 11/3.

Run from repo root: python _diagnose_session_stats.py

Compares 'gtgd' (total) vs 'gtgd_matched' (khớp lệnh only) so we can
verify whether 9/3 and 10/3 were inflated by block deals or genuinely
high-volume sessions.
"""
import json
from pathlib import Path

CACHE = Path("data_warehouse/_meta/market_session_stats.json")
if not CACHE.exists():
    print(f"Cache not found at {CACHE}")
    raise SystemExit

data = json.loads(CACHE.read_text(encoding="utf-8"))

# Compare these dates: suspected anomaly + neighbors
dates = ["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13"]
indices = ["VNINDEX", "VN30", "HNX", "UPCOM"]

print(f"\n{'='*80}")
print(f"  9h-15h session comparison: total vs matched-only vs block deal")
print(f"{'='*80}")
print(f"{'Date':<12}{'Index':<10}{'GTGD total':>14}{'GTGD matched':>16}"
      f"{'GTGD deal':>14}{'matched %':>12}{'deal %':>10}")
print("-" * 88)

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
        m_pct = (matched / total * 100) if total > 0 else 0
        d_pct = (deal / total * 100) if total > 0 else 0
        print(f"{d:<12}{idx:<10}{total:>14,.1f}{matched:>16,.1f}"
              f"{deal:>14,.1f}{m_pct:>11.1f}%{d_pct:>9.1f}%")
    print()

print("\nĐọc kết quả:")
print("  • Nếu 9/3 và 10/3 có 'GTGD deal' rất cao (% deal lớn) → block deals")
print("    bơm số tổng. matched-only sẽ ~ngang với 11/3 → confirm không phải bug.")
print("  • Nếu matched-only của 9/3 cũng cao → đó là phiên thực sự high-volume.")
