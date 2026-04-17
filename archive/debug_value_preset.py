
import sys
sys.path.insert(0, ".")
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

WAREHOUSE = Path("data_warehouse")

# 1. Kiểm tra fundamentals.parquet
fund_path = WAREHOUSE / "_meta" / "fundamentals.parquet"
print(f"fundamentals.parquet exists: {fund_path.exists()}")
if fund_path.exists():
    df = pq.read_table(str(fund_path)).to_pandas()
    print(f"  rows: {len(df)}")
    print(f"  columns: {list(df.columns)}")
    print(f"  PE not null: {df['pe'].notna().sum()}")
    print(f"  ROE not null: {df['roe'].notna().sum()}")
    print(df[df['pe'].notna()].head(3)[['ticker','pe','roe']].to_string())

# 2. Kiểm tra industry_classification.parquet
ind_path = WAREHOUSE / "_meta" / "industry_classification.parquet"
print(f"\nindustry_classification.parquet exists: {ind_path.exists()}")
if ind_path.exists():
    df2 = pq.read_table(str(ind_path), columns=["ticker","primary_industry"]).to_pandas()
    print(f"  rows: {len(df2)}")
    print(f"  sample:", df2.head(3).to_string())

# 3. Test merge
if fund_path.exists() and ind_path.exists():
    fund_df = pq.read_table(str(fund_path)).to_pandas().set_index("ticker")
    ind_df  = pq.read_table(str(ind_path), columns=["ticker","primary_industry"]).to_pandas()
    ind_df  = ind_df.rename(columns={"primary_industry":"industry"})
    merged  = fund_df.reset_index().merge(ind_df, on="ticker", how="left")
    merged["industry"] = merged["industry"].fillna("Khác")
    
    medians = {}
    for industry, grp in merged.groupby("industry"):
        pe_med  = grp["pe"].dropna().median()
        roe_med = grp["roe"].dropna().median()
        medians[industry] = {"pe": pe_med, "roe": roe_med}
    
    print(f"\nIndustry medians count: {len(medians)}")
    for k,v in list(medians.items())[:5]:
        print(f"  {k}: PE={v['pe']:.1f}, ROE={v['roe']:.1f}")
    
    # Test filter logic
    candidates = merged[merged["pe"].notna() & merged["roe"].notna()]
    print(f"\nTickers with PE+ROE: {len(candidates)}")
    
    # Join medians
    candidates = candidates.copy()
    candidates["med_pe"]  = candidates["industry"].map(lambda x: medians.get(x,{}).get("pe", float("nan")))
    candidates["med_roe"] = candidates["industry"].map(lambda x: medians.get(x,{}).get("roe", float("nan")))
    
    value_candidates = candidates[
        (candidates["pe"] > 0) &
        (candidates["pe"] < candidates["med_pe"]) &
        (candidates["roe"] > candidates["med_roe"])
    ]
    print(f"Value candidates (PE<median AND ROE>median): {len(value_candidates)}")
    if not value_candidates.empty:
        print(value_candidates[["ticker","industry","pe","med_pe","roe","med_roe"]].head(10).to_string())
