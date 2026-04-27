"""
test_shareholders.py — Kiểm tra dữ liệu cổ đông / freefloat
Chạy: python test_shareholders.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from vnstock_auth import get_vnstock, check_tier, has_sponsor_package, ensure_api_key

ensure_api_key()

print("=" * 50)
print("THONG TIN TIER")
print("=" * 50)
print("Sponsor package (vnstock_data):", has_sponsor_package())
print("API tier:", check_tier())
print()

TEST_TICKERS = ["VCB", "FPT", "VNM", "TCB", "MSN"]
SOURCES = ["KBS", "VCI"]

for ticker in TEST_TICKERS:
    print("=" * 50)
    print("TICKER:", ticker)
    print("=" * 50)
    for source in SOURCES:
        print(f"  --- Source: {source} ---")
        try:
            vn = get_vnstock(ticker, source=source)
            sh = vn.company.shareholders()
            if sh is None or sh.empty:
                print(f"  [{source}] EMPTY (khong co data)")
                continue

            print(f"  [{source}] OK - {len(sh)} co dong")
            print(f"  Columns: {list(sh.columns)}")
            print(sh.to_string(index=False))

            # Tim cot % so huu
            pct_col = None
            for col in sh.columns:
                col_lower = col.lower()
                if any(kw in col_lower for kw in ["percent", "pct", "ratio", "ownership", "own"]):
                    pct_col = col
                    break

            if pct_col:
                total = sh[pct_col].sum()
                print(f"  Tong % co dong lon: {total:.1f}%")
                print(f"  Freefloat uoc tinh: {100 - total:.1f}%")
            else:
                print(f"  Khong tim thay cot % so huu trong: {list(sh.columns)}")

        except Exception as e:
            print(f"  [{source}] LOI: {type(e).__name__}: {str(e)[:200]}")
        print()

# Also test vnstock_data if available
if has_sponsor_package():
    print("=" * 50)
    print("TEST VNSTOCK_DATA (SPONSOR/GOLDEN)")
    print("=" * 50)
    try:
        from vnstock_data import Reference
        for ticker in TEST_TICKERS[:2]:
            print(f"  Ticker: {ticker}")
            try:
                ref = Reference()
                co = ref.company(ticker)
                # Try different methods
                for method_name in ["shareholders", "ownership", "major_shareholders"]:
                    if hasattr(co, method_name):
                        try:
                            result = getattr(co, method_name)()
                            print(f"    {method_name}(): {type(result)}, shape={getattr(result, 'shape', 'N/A')}")
                            if hasattr(result, "columns"):
                                print(f"    Columns: {list(result.columns)}")
                                print(result.head(5).to_string(index=False))
                        except Exception as e2:
                            print(f"    {method_name}() LOI: {e2}")
            except Exception as e:
                print(f"  LOI: {e}")
    except ImportError:
        print("  vnstock_data khong import duoc")

print()
print("DONE.")
