# VnStock Dashboard

Nền tảng phân tích chứng khoán Việt Nam — screener, phân tích kỹ thuật/cơ bản, và tổng quan thị trường.

## Tính năng chính

- **Screener** — 9 preset lọc cổ phiếu (oversold, momentum, breakout, golden_cross, ...)
- **Phân tích** — Chart kỹ thuật (candlestick, RSI, MACD, Bollinger, VWAP) + cơ bản (P/E, ROE, EPS)
- **Thị trường** — VNINDEX/VN30/HNX, breadth indicators, heatmap ngành, dòng tiền ngoại
- **Live Mode** — Giá real-time ~1,100 mã, order book, volume profile, alerts
- **Data Pipeline** — Warehouse Parquet local, auto-update daily, AI industry classification

## Cài đặt

```bash
# Clone repo
git clone https://github.com/pichu124/vnstock-dashboard.git
cd vnstock-dashboard

# Cài dependencies
pip install -r requirements.txt
```

## Cấu hình API Key (tuỳ chọn)

Tạo file `.env` trong thư mục gốc:

```
VNSTOCK_API_KEY=vnstock_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Community tier (miễn phí): 60 requests/phút. Sponsor tiers (Golden/Silver/Bronze): 180–600 requests/phút.

## Chạy Dashboard

```bash
python -m streamlit run vnstock_dashboard.py
```

Mở trình duyệt tại `http://localhost:8501`.

## Cấu trúc dự án

```
vnstock_dashboard.py          # Main Streamlit UI (3 tabs)
vnstock_wss.py                # Real-time WSS client, batch polling
vnstock_rollup.py             # Daily rollup 1m → daily
vnstock_updater.py            # Daily price sync từ API
vnstock_screener.py           # Pattern-based stock filtering (9 presets)
vnstock_classifier.py         # AI industry classification (Claude API)
vnstock_runner.py             # Orchestrates screener runs
vnstock_warehouse.py          # Local Parquet storage helpers
scripts/                      # Windows Task Scheduler installer
docs/                         # Features & roadmap, setup guides
```

## Data Pipeline

```
data_warehouse/
├── prices/                   # OHLCV partitioned by ticker/year
│   └── ticker=VCB/year=2025/part-0.parquet
├── _live/                    # Real-time quotes & bars
│   ├── quote_VCB.json
│   └── bars_2026-04-13.parquet
└── _meta/                    # Metadata & cache
    ├── screener_results.json
    ├── fundamentals.parquet
    ├── industry_classification.parquet
    └── watchlist.json
```

## Automation (Windows)

```powershell
# Cài scheduled tasks (chạy 1 lần với quyền Admin)
powershell -ExecutionPolicy Bypass -File scripts/setup_scheduled_tasks.ps1
```

- **15:30** — Rollup 1m bars → daily warehouse
- **18:00** — Fetch daily OHLCV từ API
- **18:05** — Chạy screener 9 presets
- **Weekly** — Update fundamentals (P/E, ROE, ...)

## License

Private project.
