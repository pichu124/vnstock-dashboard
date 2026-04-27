from vnstock_market_analyzer import compute_scores, rank, format_row
import pandas as pd, json

data = json.loads(open('data_warehouse/_meta/market_overview.json', encoding='utf-8').read())
df = pd.DataFrame(data['sectors'])
idx_ret = {'1T': 0.5, '1M': 3.2, '3M': 8.1}

scores = compute_scores(df, index_returns=idx_ret)
ranked = rank(df, scores, name_col='Ngành')

print('=== TOP NGANH ===')
for r in ranked['top'][:3]:
    for ln in format_row(r, name_col='Ngành', show_detail=True):
        print(' ', ln)
    print()

print('=== ROTATION (warming up) ===')
for r in ranked.get('rotation', []):
    print(f"  {r['Ngành']:35s} rotation={r.get('rotation',0):+.1f}pp")
if not ranked.get('rotation'):
    print('  (khong co ngành nào alpha 1M vuot alpha 3M qua 5pp)')

print()
print('=== VOL REGIME ===', scores['_vol_regime'].mode()[0])

print()
print('=== NN TREND top 5 ===')
nn = scores['nn_trend'].sort_values(ascending=False)
for idx in nn.head(5).index:
    print(f"  {df.loc[idx,'Ngành']:35s} nn_trend={nn[idx]*100*20:+.2f}% cap/thang")

print()
print('=== AVOID ===')
for r in ranked['avoid'][:3]:
    print(f"  {r['Ngành']:35s} composite={r['composite']:+.2f}")
    for ln in format_row(r, name_col='Ngành', show_detail=True)[1:3]:
        print('   ', ln.strip())
