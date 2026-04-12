# VnStock Dashboard — Features & Roadmap

> Cập nhật lần cuối: 2026-04-12

---

## Tính năng hiện có

### 3 Tab chính

| Tab | Tính năng |
|---|---|
| **Screener** | Lọc cổ phiếu theo 7 preset (oversold, momentum, breakout, reversal, golden_cross, volume_surge, strong_uptrend), filter ngành/giá/volume, watchlist, alert |
| **Phân tích** | Chart kỹ thuật + cơ bản cho 1 mã, Live Mode real-time, VP, order book |
| **Thị trường** | VNINDEX/VN30/HNX trends, breadth indicators, phân bổ ngành, dòng tiền ngoại |

### Chart & Indicators

| Indicator | Mô tả | Status |
|---|---|---|
| Candlestick + Volume | LightweightCharts JS, synced crosshair 4 panel | Done |
| EMA 9/21/50/200 | Exponential Moving Averages | Done |
| Bollinger Bands 20 | Upper/Lower/Mid (2σ) | Done |
| RSI 14 | Momentum oscillator, overbought/oversold lines | Done |
| MACD 12-26-9 | MACD line + Signal + Histogram | Done |
| VWAP + bands | Volume Weighted Average Price + ±1σ/±2σ | Done (2026-04-12) |

### Live Mode

| Feature | Mô tả | Status |
|---|---|---|
| Giá real-time | ~1,100 mã HOSE+HNX+UPCOM, poll 2s | Done (2026-04-12) |
| Order book | 3 mức stock / 10 mức futures | Done |
| Volume Profile | Top 20 price levels, buy/sell breakdown | Done |
| POC (Point of Control) | Highlight mức giá volume cao nhất | Done (2026-04-12) |
| VAH/VAL (Value Area) | Vùng 70% volume, highlight + labels | Done (2026-04-12) |
| Delta Profile | Buy-Sell delta + cumulative delta | Done (2026-04-12) |
| VP on-demand (stocks) | Fetch price_depth trực tiếp khi chọn mã, cache 10s | Done (2026-04-12) |
| Quote strip | Giá/Volume/Bid/Ask/Cập nhật | Done |
| Status indicator | Connected/reconnecting/error + subscribed count | Done |

### Screener

| Feature | Mô tả | Status |
|---|---|---|
| 7 presets | oversold, overbought, momentum, breakout, reversal, golden_cross, volume_surge | Done |
| Advanced filters | Price range, %change 1D/5D/20D, volume spike multiplier | Done |
| Industry filter | Dropdown filter theo ngành (từ AI classifier) | Done |
| Watchlist | Add/remove mã yêu thích, toggle filter | Done |
| Alert tracking | Phát hiện mã mới vào/ra preset hàng ngày | Done |
| Export CSV | Xuất kết quả screener | Done |

### Fundamental Analysis

| Feature | Mô tả | Status |
|---|---|---|
| Company overview | Revenue, profit, EPS | Done |
| Financial statements | Income, balance sheet, cash flow | Done |
| Financial ratios | P/E, ROE, etc. | Done |
| Dividend history | Lịch sử chia cổ tức | Done |
| Shareholder info | Cơ cấu cổ đông | Done |
| Technical score | Composite score từ RSI/MACD/EMA/BB | Done |

### Market Overview (tab Thị trường)

| Feature | Mô tả | Status |
|---|---|---|
| Index trends | VNINDEX, VN30, HNX charts | Done |
| Breadth indicators | % above MA200, advance/decline, RSI distribution | Done |
| Sector breakdown | Phân bổ ngành, top gainers/losers | Done |
| Foreign flows | Dòng tiền ngoại | Done |

### Pipeline & Automation

| Component | Mô tả | Status |
|---|---|---|
| Updater 18:00 | Fetch daily OHLCV từ API, incremental sync | Done |
| Rollup 15:30 | Merge 1m bars → daily warehouse | Done |
| Scheduled tasks | Windows Task Scheduler, Mon-Fri | Done |
| Multi-machine | Primary/backup coordination via pipeline_status.json | Done (2026-04-12) |
| Screener runner | Chạy 7 presets, xuất screener_results.json | Done |
| AI classifier | Claude API classify ngành cho ~1,100 mã | Done |

### Data Sources

| Source | Dùng cho | Ghi chú |
|---|---|---|
| Local warehouse (Parquet) | Daily OHLCV, partitioned ticker/year | Hive-style partitioning |
| VCI API (vnstock/vnstock_data) | Intraday chart, fundamental, daily update | Golden sponsor tier |
| WSS polling (Market.price_board) | Real-time giá tất cả mã | 1 batch call mỗi 2s |
| Quote.price_depth() | Volume Profile, order book depth | On-demand cho stocks, cycle cho futures |
| screener_results.json | Kết quả screener cached | Updated by runner |
| industry_classification.parquet | Phân ngành AI | Updated by classifier |

### Modules

| File | Chức năng |
|---|---|
| `vnstock_dashboard.py` | Main Streamlit UI (3 tabs) |
| `vnstock_wss.py` | Real-time WSS client, batch polling, bar aggregation |
| `vnstock_rollup.py` | Daily rollup 1m→daily + multi-machine coordination |
| `vnstock_updater.py` | Daily price sync từ API |
| `vnstock_screener.py` | Pattern-based stock filtering (7 presets) |
| `vnstock_classifier.py` | AI industry classification (Claude API) |
| `vnstock_runner.py` | Orchestrates screener runs |
| `vnstock_warehouse.py` | Local parquet storage helpers |
| `vnstock_analysis.py` | Standalone analysis page |
| `vnstock_platform.py` | Technical indicator calculations |
| `scripts/setup_scheduled_tasks.ps1` | Windows Task Scheduler installer |

---

## Roadmap

### Ưu tiên cao (nên làm sớm)

| # | Việc | Mô tả | Status |
|---|---|---|---|
| 1 | Test live 2s poll 1,100 mã | Verify API response time, thêm fallback nếu > 2s | Pending — test thứ 2 |
| 2 | VP overlay trên chart | Render VP dạng horizontal bars trên candlestick (như TradingView) | Pending |
| 3 | Market tab live | Heatmap VN30 real-time, breadth live update | Pending |

### Ưu tiên trung bình (nâng cao trải nghiệm)

| # | Việc | Mô tả | Status |
|---|---|---|---|
| 4 | Intraday chart replay | Xem lại chart intraday sau phiên từ bars parquet | Done (2026-04-12) |
| 5 | Multi-timeframe analysis | Sidebar chọn 1m/5m/15m/1H/1D cho chart | Pending |
| 6 | Screener live | Screener trên data real-time, phát hiện breakout trong phiên | Done (2026-04-12) |
| 7 | Ticker search autocomplete | Dropdown search mã + tên công ty thay vì text input | Pending |

### Ưu tiên thấp (nice to have)

| # | Việc | Mô tả | Status |
|---|---|---|---|
| 8 | Alert system | Cảnh báo giá/volume qua Telegram/email | Pending |
| 9 | Portfolio tracker | Theo dõi danh mục cá nhân (mua/bán/P&L) | Pending |
| 10 | Dark/Light theme | Toggle giao diện | Pending |
| 11 | Mobile responsive | Tối ưu layout màn hình nhỏ | Pending |
| 12 | Export chart | Xuất chart PNG/PDF | Pending |

### Cần kiểm tra / fix

| # | Việc | Chi tiết | Status |
|---|---|---|---|
| A | Check multi-machine Monday | Verify pipeline_status.json sau rollup 15:30 + updater 18:00 | Pending — thứ 2 16:00 + 22:00 |
| B | Dọn .tmp files laptop | Có thể có .tmp rác tương tự desktop | Pending |
| C | Test price_board 1,100 mã | Verify API trả đầy đủ hay bị cắt khi batch lớn | Pending — thứ 2 |
| D | Test poll 2s response time | Nếu API response > 2s với 1,100 mã → cần skip cycle logic | Pending — thứ 2 |
| E | Test intraday replay | Bật Live Mode trong phiên → tắt → chọn Replay → verify chart 1m | Pending — thứ 2 |
| F | Test live screener | Bật Live Mode + Live Scan → verify tín hiệu update mỗi 10s | Pending — thứ 2 |
| G | Test VP on-demand stocks | Chọn mã stock (VCB, FPT) → verify VP hiện trong 1-2s | Pending — thứ 2 |
| H | Test VWAP trên chart | Verify VWAP line + bands hiện đúng trên intraday chart | Pending — thứ 2 |

---

## Changelog

### 2026-04-12
- feat: Intraday chart replay — xem lại phiên từ bars parquet (sidebar date picker)
- feat: Live Screener — scan 7 presets trên giá real-time mỗi 10s
- feat: Scale to full market ~1,100 mã, poll 2s
- feat: VP on-demand cho stocks (price_depth trực tiếp từ dashboard)
- feat: VWAP + bands trên chart
- feat: VP Advanced — POC, VAH/VAL, Delta Profile
- feat: Multi-machine primary/backup coordination (pipeline_status.json, --skip-if-done)
- feat: VP Advanced — POC, VAH/VAL, Delta Profile, cumulative delta
- feat: VWAP line + ±1σ/±2σ bands trên chart
- feat: VP on-demand cho stocks (price_depth trực tiếp từ dashboard)
- feat: Scale to full market ~1,100 mã (HOSE+HNX+UPCOM)
- perf: Poll interval giảm từ 15s → 2s (25% quota Golden)
- feat: setup_scheduled_tasks.ps1 hỗ trợ -PythonExe param
- docs: MULTI_MACHINE_SETUP.md guide cho desktop install
- fix: Dropbox Smart Sync venv workaround (C:\venvs\ ngoài Dropbox)

### 2026-04-10
- feat: Daily rollup job + health check + scheduled tasks
- fix: Volume profile preserve across price_board rounds
- fix: Atomic write with per-file locks (Windows compatibility)
- feat: 10-level order book depth for futures

### 2026-04-09
- feat: Batch polling via Market.price_board (1 request cho 30 mã)
- feat: Order book depth 3L stock / 10L futures
- feat: Futures picker in sidebar

### 2026-04-08
- feat: WSS client + VN30/Index streaming + 3-tier storage
- feat: Quote strip above chart
- fix: Price unit normalization
