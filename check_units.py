import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path

# Check 1 ticker để xem volume thực tế
ticker = "VCB"
td = Path("data_warehouse/prices") / f"ticker={ticker}"
frames = []
for yd in sorted(td.glob("year=*"))[-1:]:
    for pf in yd.glob("*.parquet"):
        frames.append(pq.read_table(str(pf), columns=["time","close","volume"]).to_pandas())

df = pd.concat(frames).sort_values("time").tail(5)
df["time"] = pd.to_datetime(df["time"])
print("VCB last 5 rows:")
print(df.to_string())
print(f"\nVolume mean: {df['volume'].mean():,.0f}")
print(f"Close mean: {df['close'].mean():,.0f}")
