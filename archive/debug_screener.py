import sys
sys.path.insert(0, ".")
from vnstock_screener import MarketScreener, _load_fundamentals, _calc_industry_medians

s = MarketScreener()
print(f"fundamentals loaded: {s.fundamentals is not None}")
if s.fundamentals is not None:
    print(f"  rows: {len(s.fundamentals)}")
    print(f"  PE not null: {s.fundamentals['pe'].notna().sum()}")

print(f"industry_medians count: {len(s.industry_medians)}")
if s.industry_medians:
    for k,v in list(s.industry_medians.items())[:3]:
        print(f"  {k}: {v}")

print(f"industry_map sample:")
sample = list(s.industry_map.items())[:3]
for t, v in sample:
    print(f"  {t}: {v}")

# Test 1 ticker
ticker = "VCB"
fund_row = (
    s.fundamentals.loc[ticker].to_dict()
    if s.fundamentals is not None and ticker in s.fundamentals.index
    else {}
)
industry = s.industry_map.get(ticker, {}).get("industry", "Khác")
med = s.industry_medians.get(industry, {})
print(f"\nVCB fund_row: pe={fund_row.get('pe')}, roe={fund_row.get('roe')}")
print(f"VCB industry: {industry}")
print(f"VCB medians: {med}")
