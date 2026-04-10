"""
vnstock_dashboard.py — VnStock Dashboard (Screener + Phân tích)
================================================================
Tab 1: Screener — lọc cổ phiếu theo preset, ngành, filter nâng cao
Tab 2: Phân tích — technical + fundamental cho một mã

Run:
  pip install streamlit plotly
  python -m streamlit run vnstock_dashboard.py
"""

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import base64 as _b64
import streamlit as st
import streamlit.components.v1 as _stc
import warnings as _warnings
_warnings.filterwarnings("ignore", message=".*st.components.v1.html.*")
import streamlit.components.v1 as _comp

# Real-time WSS client (optional)
try:
    from vnstock_wss import (
        get_wss_client,
        VN30_SYMBOLS, INDEX_SYMBOLS, FUTURES_SYMBOLS,
        is_futures,
    )
    WSS_AVAILABLE = True
except ImportError:
    WSS_AVAILABLE = False
    VN30_SYMBOLS, INDEX_SYMBOLS, FUTURES_SYMBOLS = [], [], []
    def is_futures(ticker):  # type: ignore
        return False

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="VnStock Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

RESULTS_PATH  = Path("data_warehouse/_meta/screener_results.json")
PRICES_DIR    = Path("data_warehouse/prices")
INDUSTRY_PATH = Path("data_warehouse/_meta/industry_classification.parquet")
FUND_PATH     = Path("data_warehouse/_meta/fundamentals.parquet")
WATCHLIST_PATH = Path("data_warehouse/_meta/watchlist.json")
HISTORY_DIR   = Path("data_warehouse/_meta/screener_history")

PRESET_ICONS = {
    "oversold":      "🟢",
    "overbought":    "🔴",
    "momentum":      "⚡",
    "breakout":      "🚀",
    "reversal":      "↩️",
    "golden_cross":  "✨",
    "volume_surge":  "💥",
    "strong_uptrend":"📈",
}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}

.stApp { background: #0a0e1a; }

.metric-card {
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 8px;
    padding: 16px 20px;
    text-align: center;
}
.metric-card .label {
    font-size: 11px;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}
.metric-card .value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 26px;
    font-weight: 500;
    color: #f9fafb;
}
.metric-card .sub {
    font-size: 11px;
    color: #4b5563;
    margin-top: 4px;
}

.preset-tag {
    display: inline-block;
    background: #1f2937;
    color: #9ca3af;
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 20px;
    margin: 2px;
    cursor: pointer;
}
.preset-tag.active {
    background: #065f46;
    color: #6ee7b7;
    border: 1px solid #059669;
}

.up   { color: #10b981 !important; }
.down { color: #ef4444 !important; }
.neutral { color: #9ca3af !important; }

.updated-at {
    font-size: 11px;
    color: #4b5563;
    font-family: 'IBM Plex Mono', monospace;
}

/* Dataframe styling */
[data-testid="stDataFrame"] {
    border: 1px solid #1f2937;
    border-radius: 8px;
}
.card {
    background: #111827; border: 1px solid #1f2937;
    border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
}
.card-title {
    font-size: 11px; color: #6b7280; text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 8px;
}
.section-title {
    font-size: 13px; font-weight: 500; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.06em; margin: 20px 0 10px;
}
.fscore-bar { height: 8px; border-radius: 4px; background: #1f2937; margin: 6px 0; }
.fscore-fill { height: 8px; border-radius: 4px; }
.tag { display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 500; margin: 2px; }
</style>
""", unsafe_allow_html=True)


# ── Load data ─────────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════
# Analysis functions
# ═══════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_price_history(ticker: str, days: int = 0) -> pd.DataFrame:
    """Load lịch sử giá. days=0 → toàn bộ lịch sử từ ngày lên sàn."""
    ticker_dir = PRICES_DIR / f"ticker={ticker.upper()}"
    if not ticker_dir.exists():
        return pd.DataFrame()
    frames = []
    for yd in sorted(ticker_dir.glob("year=*")):
        try:
            for pf in yd.glob("*.parquet"):
                frames.append(pq.read_table(str(pf),
                    columns=["time","open","high","low","close","volume"]).to_pandas())
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    if days > 0:
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["time"] >= cutoff]
    return df.sort_values("time").reset_index(drop=True)


@st.cache_data(ttl=600)
def load_screener_results() -> dict:
    if not RESULTS_PATH.exists():
        return {}
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=600)
def load_industry_map() -> dict:
    if not INDUSTRY_PATH.exists():
        return {}
    try:
        df = pq.read_table(str(INDUSTRY_PATH),
                           columns=["ticker","company_name","primary_industry",
                                    "secondary_industries","business_summary"]).to_pandas()
        result = {}
        for _, row in df.iterrows():
            result[str(row["ticker"])] = {
                "company_name":    str(row.get("company_name", "")),
                "industry":        str(row.get("primary_industry", "")),
                "secondary":       str(row.get("secondary_industries", "[]")),
                "business_summary": str(row.get("business_summary", "")),
            }
        return result
    except Exception:
        return {}


def get_all_tickers() -> list:
    if not PRICES_DIR.exists():
        return []
    import re as _re
    _CW  = _re.compile(r"^C[A-Z]{2,4}\d{4}$")
    _OLD = _re.compile(r"^[A-Z]{2,4}\d{5,6}$")
    _FUT = _re.compile(r"^[A-Z]{2,6}F\d{4}$")
    _FT2 = _re.compile(r"^[A-Z]{2}\d{2}F\d{4}$")
    def ok(s):
        s = s.upper()
        if not s or s[0].isdigit(): return False
        return not (_CW.match(s) or _OLD.match(s) or _FUT.match(s) or _FT2.match(s))
    return sorted([
        p.name.replace("ticker=", "")
        for p in PRICES_DIR.iterdir()
        if p.is_dir() and p.name.startswith("ticker=")
        and ok(p.name.replace("ticker=", ""))
    ])


# ═════════════════════════════════════════════════════════════════════════════
# Technical Analysis (pure pandas)
# ═════════════════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"].astype(float)

    # RSI 14
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # EMAs
    for span in (9, 21, 50, 200):
        df[f"ema{span}"] = c.ewm(span=span, adjust=False).mean()

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # Bollinger Bands 20
    sma20       = c.rolling(20).mean()
    std20       = c.rolling(20).std()
    df["bb_up"] = sma20 + 2 * std20
    df["bb_lo"] = sma20 - 2 * std20
    df["bb_mid"]= sma20

    # Volume MA20
    df["vol_ma20"] = df["volume"].astype(float).rolling(20).mean()

    return df


def get_tech_signals(df: pd.DataFrame) -> dict:
    ind = compute_indicators(df)
    if ind.empty:
        return {}
    lat = ind.iloc[-1]
    prv = ind.iloc[-2] if len(ind) > 1 else lat

    price = float(lat["close"])
    rsi   = float(lat["rsi"]) if not np.isnan(lat["rsi"]) else None
    macd_h = float(lat["macd_hist"]) if not np.isnan(lat["macd_hist"]) else None
    macd_ph = float(prv["macd_hist"]) if not np.isnan(prv["macd_hist"]) else None

    # Change
    chg1d  = round((price / float(prv["close"]) - 1) * 100, 2) if len(ind) > 1 else None
    chg5d  = round((price / float(ind.iloc[-6]["close"]) - 1) * 100, 2) if len(ind) > 5 else None
    chg20d = round((price / float(ind.iloc[-21]["close"]) - 1) * 100, 2) if len(ind) > 20 else None

    # 52W
    yr = ind.tail(252)
    hi52 = float(yr["high"].max()) if not yr.empty else None
    lo52 = float(yr["low"].min())  if not yr.empty else None
    pct52 = round((price - lo52) / (hi52 - lo52) * 100, 1) if hi52 and lo52 and hi52 != lo52 else None

    # Signals
    rsi_sig = "BUY" if rsi and rsi < 30 else ("SELL" if rsi and rsi > 70 else "NEUTRAL")

    if macd_h is None or macd_ph is None:
        macd_sig = "NEUTRAL"
    elif macd_h > 0 and macd_ph <= 0:
        macd_sig = "BUY"
    elif macd_h < 0 and macd_ph >= 0:
        macd_sig = "SELL"
    else:
        macd_sig = "BUY" if macd_h > 0 else "SELL"

    e9  = float(lat["ema9"])  if not np.isnan(lat["ema9"])  else None
    e21 = float(lat["ema21"]) if not np.isnan(lat["ema21"]) else None
    e50 = float(lat["ema50"]) if not np.isnan(lat.get("ema50", np.nan)) else None
    e200= float(lat["ema200"]) if not np.isnan(lat.get("ema200", np.nan)) else None
    ema_sig = "BUY" if (e9 and e21 and e9 > e21) else ("SELL" if (e9 and e21) else "NEUTRAL")

    bb_up = float(lat["bb_up"]) if not np.isnan(lat["bb_up"]) else None
    bb_lo = float(lat["bb_lo"]) if not np.isnan(lat["bb_lo"]) else None
    if bb_up and bb_lo:
        bb_sig = "SELL" if price >= bb_up else ("BUY" if price <= bb_lo else "NEUTRAL")
        bb_pct = round((price - bb_lo) / (bb_up - bb_lo) * 100, 1)
    else:
        bb_sig, bb_pct = "NEUTRAL", None

    vol      = float(lat["volume"])
    vol_ma20 = float(lat["vol_ma20"]) if not np.isnan(lat["vol_ma20"]) else None
    vol_spike = round(vol / vol_ma20, 2) if vol_ma20 and vol_ma20 > 0 else None

    # Tech score
    m = {"BUY": 1, "NEUTRAL": 0, "SELL": -1}
    tech_score = round((
        m[rsi_sig]*1.5 + m[macd_sig]*1.5 + m[ema_sig]*1.0 + m[bb_sig]*0.5
    ) / 4.5, 4)

    return {
        "price": price, "chg1d": chg1d, "chg5d": chg5d, "chg20d": chg20d,
        "rsi": rsi, "rsi_sig": rsi_sig,
        "macd_hist": macd_h, "macd_sig": macd_sig,
        "ema9": e9, "ema21": e21, "ema50": e50, "ema200": e200,
        "ema_sig": ema_sig,
        "bb_up": bb_up, "bb_lo": bb_lo, "bb_pct": bb_pct, "bb_sig": bb_sig,
        "vol": vol, "vol_ma20": vol_ma20, "vol_spike": vol_spike,
        "hi52": hi52, "lo52": lo52, "pct52": pct52,
        "tech_score": tech_score,
        "df_ind": ind,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Chart renderer (Plotly via st.plotly_chart)
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# Real-time WSS helpers
# ═════════════════════════════════════════════════════════════════════════════

LIVE_DIR = Path("data_warehouse/_live")


def load_live_quote(ticker: str) -> dict | None:
    """Đọc live quote snapshot từ Tầng 1 (vnstock_wss)."""
    path = LIVE_DIR / f"quote_{ticker.upper()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def render_order_book(bids: list, asks: list, scale: float = 1.0,
                      max_levels: int = 3, title: str = "📋 Sổ lệnh"):
    """
    Render order book table side-by-side (bid bên trái, ask bên phải).
    bids/asks: list of dict {"price", "volume"} — đã sorted best → kém.
    scale: chia giá cho scale nếu cần normalize đơn vị (vd 1000).
    max_levels: 3 cho cổ phiếu, 10 cho hợp đồng tương lai.
    """
    if not bids and not asks:
        return

    def _fmt_price(v):
        try:
            return f"{float(v) / scale:,.2f}"
        except Exception:
            return "—"

    def _fmt_vol(v):
        try:
            return f"{int(float(v)):,}"
        except Exception:
            return "—"

    rows_html = ""
    for i in range(max_levels):
        bid = bids[i] if i < len(bids) else None
        ask = asks[i] if i < len(asks) else None
        bp = _fmt_price(bid["price"]) if bid else "—"
        bv = _fmt_vol(bid.get("volume")) if bid and bid.get("volume") else "—"
        ap = _fmt_price(ask["price"]) if ask else "—"
        av = _fmt_vol(ask.get("volume")) if ask and ask.get("volume") else "—"
        rank_label = f"{i+1}" if i < 3 else f"{i+1}"
        rows_html += (
            f"<tr>"
            f"<td style='color:#6b7280;text-align:center;padding:4px 6px;"
            f"font-size:10px'>{rank_label}</td>"
            f"<td style='color:#9ca3af;text-align:right;padding:4px 10px'>{bv}</td>"
            f"<td style='color:#10b981;text-align:right;padding:4px 10px;"
            f"font-weight:600;background:rgba(16,185,129,0.08)'>{bp}</td>"
            f"<td style='color:#ef4444;text-align:left;padding:4px 10px;"
            f"font-weight:600;background:rgba(239,68,68,0.08)'>{ap}</td>"
            f"<td style='color:#9ca3af;text-align:left;padding:4px 10px'>{av}</td>"
            f"</tr>"
        )

    html = (
        f"<div style='margin:10px 0 16px 0'>"
        f"<div style='color:#9ca3af;font-size:11px;margin-bottom:6px;"
        f"text-transform:uppercase;letter-spacing:0.08em;font-weight:500'>{title}</div>"
        f"<table style='width:100%;font-family:IBM Plex Mono,monospace;"
        f"font-size:13px;border-collapse:collapse;"
        f"border:1px solid #1f2937;border-radius:6px;overflow:hidden'>"
        f"<thead><tr style='color:#6b7280;font-size:10px;"
        f"text-transform:uppercase;letter-spacing:0.05em;background:#111827'>"
        f"<th style='text-align:center;padding:6px;width:24px'>#</th>"
        f"<th style='text-align:right;padding:6px 10px'>KL Mua</th>"
        f"<th style='text-align:right;padding:6px 10px'>Giá Mua</th>"
        f"<th style='text-align:left;padding:6px 10px'>Giá Bán</th>"
        f"<th style='text-align:left;padding:6px 10px'>KL Bán</th>"
        f"</tr></thead>"
        f"<tbody>{rows_html}</tbody></table></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _normalize_live_price(historical_last_close: float, live_price: float) -> float:
    """
    Chuẩn hoá đơn vị giá live cho khớp với scale của chart historical.
    vnstock thường trả intraday dạng thousand (25.55 = 25,550đ) trong khi
    Market.price_board() trả giá VND thật (25550). Khi merge trực tiếp
    sẽ phá scale của chart.
    """
    if historical_last_close <= 0 or live_price <= 0:
        return live_price
    ratio = live_price / historical_last_close
    if ratio > 100:
        # Live cao gấp ~1000x → historical ở dạng thousand
        return live_price / 1000.0
    if ratio < 0.01:
        # Live thấp hơn ~1000x → historical ở VND
        return live_price * 1000.0
    return live_price


def _merge_live_quote(df: pd.DataFrame, quote: dict) -> pd.DataFrame:
    """Merge live quote vào bar cuối cùng hoặc append bar mới."""
    if df.empty or not quote or not quote.get("price"):
        return df
    try:
        tick_time = pd.to_datetime(quote["time"])
        if hasattr(tick_time, "tz") and tick_time.tz is not None:
            tick_time = tick_time.tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
        bar_time = tick_time.floor("1min")
        df = df.copy()
        last_time = pd.to_datetime(df.iloc[-1]["time"])
        last_close = float(df.iloc[-1]["close"])
        price = _normalize_live_price(last_close, float(quote["price"]))
        if last_time == bar_time:
            idx = df.index[-1]
            df.at[idx, "high"] = max(float(df.at[idx, "high"]), price)
            df.at[idx, "low"] = min(float(df.at[idx, "low"]), price)
            df.at[idx, "close"] = price
        else:
            new_row = {
                "time": bar_time,
                "open": price, "high": price,
                "low": price, "close": price,
                "volume": float(quote.get("volume", 0)),
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        return df
    except Exception:
        return df


@st.cache_resource
def _get_wss_singleton():
    """Singleton WSS client — start once per Streamlit process."""
    if not WSS_AVAILABLE:
        return None
    try:
        client = get_wss_client()
        client.start()
        client.subscribe_all()
        return client
    except Exception as e:
        print(f"[dashboard] WSS start failed: {e}")
        return None


@st.cache_data(ttl=120, show_spinner=False)
def load_intraday(ticker: str, interval: str = "15m") -> pd.DataFrame:
    """Fetch intraday OHLCV từ VCI. interval: '1m','5m','15m','30m','1H'"""
    try:
        from datetime import date as _d, timedelta as _td
        lookback = {"1m":5,"5m":30,"15m":60,"30m":60,"1H":90}.get(interval, 10)
        end   = _d.today().strftime("%Y-%m-%d")
        start = (_d.today() - _td(days=lookback)).strftime("%Y-%m-%d")
        from vnstock import Vnstock
        df = Vnstock().stock(symbol=ticker, source="VCI").quote.history(
            start=start, end=end, interval=interval)
        if df is None or df.empty:
            return pd.DataFrame()
        needed = ["time","open","high","low","close","volume"]
        if not all(c in df.columns for c in needed):
            col_map = {}
            for c in df.columns:
                cl = c.lower()
                if cl in ("time","date","tradingdate"): col_map[c] = "time"
                elif cl == "open":   col_map[c] = "open"
                elif cl == "high":   col_map[c] = "high"
                elif cl == "low":    col_map[c] = "low"
                elif cl in ("close","adjclose"): col_map[c] = "close"
                elif cl in ("volume","vol"):     col_map[c] = "volume"
            df = df.rename(columns=col_map)
        if not all(c in df.columns for c in needed):
            return pd.DataFrame()
        df = df[needed].copy()
        df["time"] = pd.to_datetime(df["time"])
        # Convert UTC → UTC+7 nếu cần
        if df["time"].dt.tz is not None:
            df["time"] = df["time"].dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
        else:
            sample_hour = df["time"].dt.hour.median()
            if sample_hour < 5:
                df["time"] = df["time"] + pd.Timedelta(hours=7)
        # Lọc giờ giao dịch HOSE
        if interval not in ("1D","1W","1M"):
            mask = (df["time"].dt.hour >= 9) & (df["time"].dt.hour < 15)
            df = df[mask]
        return df.sort_values("time").reset_index(drop=True)
    except Exception as e:
        print(f"[load_intraday] {ticker} {interval}: {e}")
        return pd.DataFrame()


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample daily OHLCV sang weekly/monthly."""
    if df.empty:
        return df
    df2 = df.copy()
    df2["time"] = pd.to_datetime(df2["time"])
    df2 = df2.set_index("time")
    resampled = df2.resample(rule).agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna().reset_index()
    return resampled


@st.cache_data(ttl=3600, show_spinner=False)
def load_fundamental(ticker: str) -> dict:
    """Load ratios từ vnstock — hỗ trợ MultiIndex tuple columns."""
    result = {}
    try:
        try:
            from vnstock_data import Fundamental
            ratios = Fundamental().equity(ticker).ratio(period="Y")
        except ImportError:
            from vnstock import Vnstock
            ratios = Vnstock().stock(symbol=ticker, source="VCI").finance.ratio(period="year", lang="vi")
        if ratios is None or ratios.empty:
            result["error"] = "Không có dữ liệu"
            return result
        def get_val(df, *keys):
            row = df.iloc[0]
            for key in keys:
                key_lo = key.lower()
                for col in df.columns:
                    col_str = " ".join(str(c) for c in col).lower() if isinstance(col, tuple) else str(col).lower()
                    if key_lo in col_str:
                        try:
                            v = row[col]
                            return float(v) if v is not None and not pd.isna(v) else None
                        except Exception:
                            continue
            return None
        result["pe"]         = get_val(ratios, "p/e")
        result["pb"]         = get_val(ratios, "p/b")
        result["roe"]        = get_val(ratios, "roe (%)")
        result["roa"]        = get_val(ratios, "roa (%)")
        result["eps"]        = get_val(ratios, "eps (vnd)")
        result["net_margin"] = get_val(ratios, "biên lợi nhuận ròng")
        result["gross_margin"] = get_val(ratios, "biên lợi nhuận gộp")
        result["debt_ratio"] = get_val(ratios, "đòn bẩy tài chính")
        for key in ("roe","roa","net_margin","gross_margin"):
            if result.get(key) is not None and abs(result[key]) <= 2:
                result[key] = round(result[key] * 100, 2)
    except Exception as e:
        result["error"] = str(e)[:120]
    return result

def render_chart(df: pd.DataFrame, ticker: str, height: int = 850):
    """
    TradingView lightweight-charts — inline JS (no CDN needed).
    Fast, no weekend gaps, synced crosshair across all panels.
    """
    import json as _json

    ind = compute_indicators(df)
    if ind.empty or len(ind) < 2:
        st.warning("Không đủ dữ liệu để vẽ chart.")
        return

    def safe(val):
        try:
            v = float(val)
            return None if v != v else round(v, 4)
        except Exception:
            return None

    def ts(t):
        return int(pd.Timestamp(t).timestamp())

    candles, volumes = [], []
    ema9_d, ema21_d, ema50_d, ema200_d = [], [], [], []
    bb_up_d, bb_lo_d, bb_mid_d = [], [], []
    rsi_d, macd_l, macd_s, macd_h = [], [], [], []

    for _, row in ind.iterrows():
        t = ts(row["time"])
        o, h, l, c = safe(row["open"]), safe(row["high"]), safe(row["low"]), safe(row["close"])
        v = safe(row["volume"])
        if None in (o, h, l, c):
            continue
        candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
        col = "rgba(16,185,129,0.6)" if c >= o else "rgba(239,68,68,0.6)"
        volumes.append({"time": t, "value": v or 0, "color": col})
        if (x := safe(row.get("ema9")))       is not None: ema9_d.append({"time":t,"value":x})
        if (x := safe(row.get("ema21")))      is not None: ema21_d.append({"time":t,"value":x})
        if (x := safe(row.get("ema50")))      is not None: ema50_d.append({"time":t,"value":x})
        if (x := safe(row.get("ema200")))     is not None: ema200_d.append({"time":t,"value":x})
        if (x := safe(row.get("bb_up")))      is not None: bb_up_d.append({"time":t,"value":x})
        if (x := safe(row.get("bb_lo")))      is not None: bb_lo_d.append({"time":t,"value":x})
        if (x := safe(row.get("bb_mid")))     is not None: bb_mid_d.append({"time":t,"value":x})
        if (x := safe(row.get("rsi")))        is not None: rsi_d.append({"time":t,"value":x})
        if (x := safe(row.get("macd")))       is not None: macd_l.append({"time":t,"value":x})
        if (x := safe(row.get("macd_signal"))) is not None: macd_s.append({"time":t,"value":x})
        if (x := safe(row.get("macd_hist")))  is not None:
            macd_h.append({"time":t,"value":x,"color":"rgba(16,185,129,0.8)" if x>=0 else "rgba(239,68,68,0.8)"})

    if not candles:
        st.warning("Không có dữ liệu hợp lệ để vẽ chart.")
        return

    last_price = candles[-1]["close"]
    LWC_JS = __import__("pathlib").Path(__file__).parent / "lwc.min.js"
    try:
        lwc_code = LWC_JS.read_text(encoding="utf-8")
    except Exception:
        lwc_code = ""

    html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0e1a; font-family:monospace; color:#9ca3af; }
#wrapper { display:flex; flex-direction:column; height:100vh; padding:6px; gap:4px; }
.lbl { font-size:10px; color:#6b7280; text-transform:uppercase; padding:2px 4px; }
.ohlcv { font-size:11px; padding:1px 4px; min-height:16px; }
#mw { flex:5; display:flex; flex-direction:column; min-height:0; }
#vw { flex:1.5; display:flex; flex-direction:column; min-height:0; }
#rw { flex:1.5; display:flex; flex-direction:column; min-height:0; }
#dw { flex:1.5; display:flex; flex-direction:column; min-height:0; }
#mc,#vc,#rc,#dc { flex:1; min-height:0; }
</style>
<script>""" + lwc_code + """</script>
</head>
<body>
<div id="wrapper">
  <div id="mw">
    <div class="lbl">""" + ticker + """ · Candlestick · EMA · BB</div>
    <div class="ohlcv" id="ohlcv">O — H — L — C —</div>
    <div id="mc"></div>
  </div>
  <div id="vw"><div class="lbl">Volume</div><div id="vc"></div></div>
  <div id="rw"><div class="lbl">RSI (14)</div><div id="rc"></div></div>
  <div id="dw"><div class="lbl">MACD (12,26,9)</div><div id="dc"></div></div>
</div>
<script>
var C=""" + _json.dumps(candles) + """;
var V=""" + _json.dumps(volumes) + """;
var E9=""" + _json.dumps(ema9_d) + """;
var E21=""" + _json.dumps(ema21_d) + """;
var E50=""" + _json.dumps(ema50_d) + """;
var E200=""" + _json.dumps(ema200_d) + """;
var BU=""" + _json.dumps(bb_up_d) + """;
var BL=""" + _json.dumps(bb_lo_d) + """;
var BM=""" + _json.dumps(bb_mid_d) + """;
var RSI=""" + _json.dumps(rsi_d) + """;
var ML=""" + _json.dumps(macd_l) + """;
var MS=""" + _json.dumps(macd_s) + """;
var MH=""" + _json.dumps(macd_h) + """;
var LP=""" + str(last_price) + """;

var BASE={
  layout:{background:{color:"#0d1117"},textColor:"#9ca3af",fontSize:11},
  grid:{vertLines:{color:"#1a2234"},horzLines:{color:"#1a2234"}},
  crosshair:{
    mode:LightweightCharts.CrosshairMode.Normal,
    vertLine:{color:"#4b5563",width:1,style:1,labelBackgroundColor:"#1f2937"},
    horzLine:{color:"#4b5563",width:1,style:1,labelBackgroundColor:"#1f2937"},
  },
  rightPriceScale:{borderColor:"#1f2937"},
  timeScale:{borderColor:"#1f2937",timeVisible:true,secondsVisible:false,rightOffset:5},
  handleScroll:{mouseWheel:true,pressedMouseMove:true},
  handleScale:{mouseWheel:true,pinch:true},
};

function mk(id,extra){
  var el=document.getElementById(id);
  var o=Object.assign({},BASE,extra||{},{width:el.clientWidth,height:el.clientHeight});
  return LightweightCharts.createChart(el,o);
}

var main=mk("mc");
var cs=main.addCandlestickSeries({
  upColor:"#10b981",downColor:"#ef4444",
  borderUpColor:"#10b981",borderDownColor:"#ef4444",
  wickUpColor:"#059669",wickDownColor:"#dc2626",
});
cs.setData(C);
cs.createPriceLine({price:LP,color:"#fbbf24",lineWidth:1,
  lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:""});

function line(chart,data,color,width,title,lvVisible){
  if(!data||!data.length) return;
  chart.addLineSeries({color:color,lineWidth:width||1,title:title||"",
    lastValueVisible:lvVisible!==false,priceLineVisible:false}).setData(data);
}
line(main,E9,"#60a5fa",1,"EMA9");
line(main,E21,"#c084fc",1,"EMA21");
line(main,E50,"#fbbf24",1.5,"EMA50");
line(main,E200,"#f97316",2,"EMA200");
line(main,BU,"rgba(139,92,246,0.5)",1,"BB+",false);
line(main,BL,"rgba(139,92,246,0.5)",1,"BB-",false);
line(main,BM,"rgba(139,92,246,0.25)",1,"",false);

main.subscribeCrosshairMove(function(p){
  if(!p.time) return;
  var d=p.seriesData.get(cs);
  if(!d) return;
  document.getElementById("ohlcv").innerHTML=
    "O <b style='color:#e5e7eb'>"+d.open.toFixed(2)+"</b>  "+
    "H <b style='color:#10b981'>"+d.high.toFixed(2)+"</b>  "+
    "L <b style='color:#ef4444'>"+d.low.toFixed(2)+"</b>  "+
    "C <b style='color:#fbbf24'>"+d.close.toFixed(2)+"</b>";
});

var vol=mk("vc",{rightPriceScale:{scaleMargins:{top:0.1,bottom:0}}});
vol.addHistogramSeries({priceFormat:{type:"volume"},priceScaleId:""}).setData(V);

var rsi=mk("rc",{rightPriceScale:{scaleMargins:{top:0.1,bottom:0.1}}});
line(rsi,RSI,"#a78bfa",1.5,"RSI",true);
if(RSI.length){
  line(rsi,RSI.map(function(d){return{time:d.time,value:70}}),"rgba(239,68,68,0.4)",1,"",false);
  line(rsi,RSI.map(function(d){return{time:d.time,value:30}}),"rgba(16,185,129,0.4)",1,"",false);
}

var mac=mk("dc",{rightPriceScale:{scaleMargins:{top:0.1,bottom:0.1}}});
if(MH.length) mac.addHistogramSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false}).setData(MH);
line(mac,ML,"#60a5fa",1.5,"MACD",true);
line(mac,MS,"#f97316",1.5,"Signal",true);

var charts=[main,vol,rsi,mac];
charts.forEach(function(s){
  s.subscribeCrosshairMove(function(p){
    if(!p.time) return;
    charts.forEach(function(t){
      if(t!==s) t.setCrosshairPosition(NaN,p.time,null);
    });
  });
  s.timeScale().subscribeVisibleLogicalRangeChange(function(){
    var r=s.timeScale().getVisibleLogicalRange();
    if(!r) return;
    charts.forEach(function(t){if(t!==s) t.timeScale().setVisibleLogicalRange(r);});
  });
});

function resize(){
  var ids=["mc","vc","rc","dc"];
  [main,vol,rsi,mac].forEach(function(c,i){
    var el=document.getElementById(ids[i]);
    c.resize(el.clientWidth,el.clientHeight);
  });
}
window.addEventListener("resize",resize);
setTimeout(resize,100);
</script>
</body>
</html>"""

    _stc.html(html, height=height, scrolling=False)




# ═════════════════════════════════════════════════════════════════════════════
# UI Helpers
# ═════════════════════════════════════════════════════════════════════════════

def sig_color(sig: str) -> str:
    if sig == "BUY":     return "#10b981"
    if sig == "SELL":    return "#ef4444"
    return "#9ca3af"

def pct_color(v) -> str:
    if v is None: return "#6b7280"
    return "#10b981" if v > 0 else ("#ef4444" if v < 0 else "#9ca3af")

def fmt_pct(v) -> str:
    if v is None: return "—"
    return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"

def fmt_num(v, decimals=2) -> str:
    if v is None: return "—"
    return f"{v:.{decimals}f}"


def render_signal_badge(label: str, sig: str):
    color = sig_color(sig)
    bg = "#064e3b" if sig=="BUY" else ("#450a0a" if sig=="SELL" else "#1f2937")
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;'
        f'align-items:center;padding:6px 0;border-bottom:1px solid #1f2937">'
        f'<span style="font-size:13px;color:#9ca3af">{label}</span>'
        f'<span style="background:{bg};color:{color};font-size:11px;'
        f'font-weight:600;padding:3px 10px;border-radius:20px">{sig}</span>'
        f'</div>',
        unsafe_allow_html=True
    )


def render_metric_row(items: list):
    """items = [(label, value, sub), ...]"""
    cols = st.columns(len(items))
    for col, (label, value, sub) in zip(cols, items):
        with col:
            color = "#f9fafb"
            if isinstance(value, str) and value.startswith("+"):
                color = "#10b981"
            elif isinstance(value, str) and value.startswith("-"):
                color = "#ef4444"
            st.markdown(
                f'<div class="card">'
                f'<div class="card-title">{label}</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:22px;'
                f'font-weight:500;color:{color}">{value}</div>'
                f'<div style="font-size:11px;color:#4b5563;margin-top:4px">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True
            )


# ═════════════════════════════════════════════════════════════════════════════
# Main App
# ═════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# Screener functions
# ═══════════════════════════════════════════════════════

@st.cache_data(ttl=300)  # Cache 5 phút
def load_results():
    if not RESULTS_PATH.exists():
        return None
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── Watchlist ──────────────────────────────────────────────────────────────────

def load_watchlist() -> list:
    if WATCHLIST_PATH.exists():
        try:
            with open(WATCHLIST_PATH, encoding="utf-8") as f:
                return json.load(f).get("tickers", [])
        except Exception:
            pass
    return []


def save_watchlist(tickers: list):
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump({"tickers": sorted(set(tickers)), "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


# ── Alerts ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def compute_alerts(current_generated_at: str) -> list:
    """So sánh screener results hôm nay vs hôm qua → list alerts."""
    if not HISTORY_DIR.exists():
        return []
    try:
        today_data = load_results()
        if not today_data:
            return []

        # Tìm file hôm qua (thử 3 ngày gần nhất cho weekend)
        prev_data = None
        for days_back in range(1, 4):
            prev_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            prev_path = HISTORY_DIR / f"{prev_date}.json"
            if prev_path.exists():
                with open(prev_path, encoding="utf-8") as f:
                    prev_data = json.load(f)
                break

        if not prev_data:
            return []

        alerts = []
        for preset, info in today_data.get("presets", {}).items():
            current_tickers = {r["ticker"] for r in info.get("results", [])}
            prev_info = prev_data.get("presets", {}).get(preset, {})
            prev_tickers = {r["ticker"] for r in prev_info.get("results", [])}

            for t in current_tickers - prev_tickers:
                alerts.append({"type": "new", "ticker": t, "preset": preset})
            for t in prev_tickers - current_tickers:
                alerts.append({"type": "removed", "ticker": t, "preset": preset})

        return sorted(alerts, key=lambda a: (a["type"] != "new", a["preset"], a["ticker"]))
    except Exception:
        return []


def format_pct(val):
    """Format percentage với màu."""
    if val is None:
        return "—"
    try:
        v = float(val)
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.1f}%"
    except Exception:
        return "—"


def color_pct(val):
    """Return color class cho pct."""
    if val is None:
        return "neutral"
    try:
        return "up" if float(val) > 0 else ("down" if float(val) < 0 else "neutral")
    except Exception:
        return "neutral"


def df_from_preset(preset_data: dict) -> pd.DataFrame:
    """Convert preset results sang DataFrame đã format."""
    if not preset_data.get("results"):
        return pd.DataFrame()

    df = pd.DataFrame(preset_data["results"])
    if df.empty:
        return df

    # Chọn và rename columns
    col_map = {
        "ticker":      "Ticker",
        "industry":    "Ngành",
        "last_close":  "Giá",
        "chg_1d_pct":  "1D%",
        "chg_5d_pct":  "5D%",
        "chg_20d_pct": "20D%",
        "rsi_14":      "RSI",
        "macd_cross":  "MACD",
        "ema_trend":   "Trend",
        "vol_spike":   "Vol×",
        "bb_pct":      "BB%",
        "52w_pct":     "52W%",
    }

    cols_available = [c for c in col_map if c in df.columns]
    df = df[cols_available].rename(columns={c: col_map[c] for c in cols_available})

    # Format numbers
    for col in ["1D%", "5D%", "20D%", "BB%", "52W%"]:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: f"+{v:.1f}%" if v and v > 0 else (f"{v:.1f}%" if v else "—")
            )
    for col in ["RSI", "Vol×"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda v: f"{v:.1f}" if v else "—")
    if "Giá" in df.columns:
        df["Giá"] = df["Giá"].apply(lambda v: f"{v:,.1f}" if v else "—")

    return df


# ── Styler ───────────────────────────────────────────────────────────────────

def render_table(df: pd.DataFrame, top_n: int = 50):
    """HTML table với màu sắc + click-to-sort, dùng components.html."""
    import streamlit.components.v1 as _comp
    import json as _json

    display = df.head(top_n).copy().reset_index(drop=True)
    cols = list(display.columns)

    # Build rows JSON để JS sort — thêm __idx để map DOM↔data
    rows_data = []
    for i, (_, row) in enumerate(display.iterrows()):
        r = {"__idx": str(i)}
        for col in cols:
            v = row.get(col)
            r[col] = str(v) if v is not None else "—"
        rows_data.append(r)

    def cell_color(col, val):
        if not val or val == "—": return "#4b5563"
        if col in ("1D%","5D%","20D%","BB%","52W%"):
            try:
                v = float(str(val).replace("%","").replace("+",""))
                return "#10b981" if v>0 else ("#ef4444" if v<0 else "#9ca3af")
            except: return "#6b7280"
        if col == "RSI":
            try:
                v = float(val)
                if v<30: return "#10b981"
                if v>70: return "#ef4444"
                if v<40: return "#6ee7b7"
                if v>60: return "#fca5a5"
                return "#e5e7eb"
            except: return "#6b7280"
        if col == "MACD":
            m={"BUY":"#10b981","BULL":"#34d399","SELL":"#ef4444","BEAR":"#f87171"}
            return m.get(str(val).upper(),"#9ca3af")
        if col == "Trend":
            return "#10b981" if str(val).upper()=="UP" else ("#ef4444" if str(val).upper() in ("DOWN","DN") else "#9ca3af")
        if col == "Ticker": return "#60a5fa"
        if col == "Ngành":  return "#a78bfa"
        return "#d1d5db"

    def cell_weight(col, val):
        if col == "Ticker": return "600"
        if col in ("1D%","5D%","20D%","BB%","52W%"):
            try: return "500" if float(str(val).replace("%","").replace("+",""))!=0 else "400"
            except: return "400"
        if col == "RSI":
            try: return "700" if (float(val)<30 or float(val)>70) else "400"
            except: return "400"
        if col == "MACD" and str(val).upper() in ("BUY","SELL"): return "700"
        return "400"

    # Build rows HTML
    rows_html_parts = []
    for i, rd in enumerate(rows_data):
        bg = "#0d1117" if i%2==0 else "#111827"
        cells = []
        for col in cols:
            val = rd.get(col,"—")
            color  = cell_color(col, val)
            weight = cell_weight(col, val)
            fs = "12px" if col=="Ngành" else "13px"
            cells.append(
                f'<td style="padding:7px 12px;border-bottom:1px solid #1a2234;'
                f'white-space:nowrap;color:{color};font-weight:{weight};font-size:{fs};">'
                f'{val}</td>'
            )
        rows_html_parts.append(
            f'<tr data-idx="{i}" data-bg="{bg}" style="background:{bg};">'
            + "".join(cells) + "</tr>"
        )

    rows_html = "\n".join(rows_html_parts)
    rows_json  = _json.dumps(rows_data,  ensure_ascii=False)
    cols_json  = _json.dumps(cols, ensure_ascii=False)

    height = min(680, 52 + len(display)*35)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:#0a0e1a; font-family:'IBM Plex Mono',monospace; overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; }}
  thead th {{
    background:#111827; color:#6b7280; font-size:11px; font-weight:500;
    text-transform:uppercase; letter-spacing:0.06em;
    padding:10px 12px; border-bottom:2px solid #1f2937;
    white-space:nowrap; cursor:pointer; user-select:none;
    font-family:'IBM Plex Sans',sans-serif;
  }}
  thead th:hover {{ color:#e5e7eb; background:#1a2234; }}
  thead th .arrow {{ margin-left:4px; opacity:0.3; font-size:10px; }}
  thead th.active .arrow {{ opacity:1; color:#60a5fa; }}
  tbody tr:hover td {{ background:#1e2a3a !important; }}
</style>
</head>
<body>
<table id="t">
<thead>
<tr id="header-row"></tr>
</thead>
<tbody id="tbody">
{rows_html}
</tbody>
</table>
<script>
var COLS = {cols_json};
var ROWS = {rows_json};
var sortCol = null, sortAsc = true;

// Build headers
var hr = document.getElementById("header-row");
COLS.forEach(function(col) {{
  var th = document.createElement("th");
  th.innerHTML = col + '<span class="arrow">⇅</span>';
  th.onclick = function() {{ doSort(col, th); }};
  th.dataset.col = col;
  hr.appendChild(th);
}});

function parseNum(v) {{
  if (!v || v==="—" || v==="None") return null;
  var n = parseFloat(v.replace(/[%+,x×]/g,""));
  return isNaN(n) ? v.toLowerCase() : n;
}}

function doSort(col, th) {{
  if (sortCol===col) {{ sortAsc = !sortAsc; }}
  else {{ sortCol=col; sortAsc=true; }}

  // Reset all arrows
  document.querySelectorAll("thead th").forEach(function(h) {{
    h.classList.remove("active");
    h.querySelector(".arrow").textContent = "⇅";
  }});
  th.classList.add("active");
  th.querySelector(".arrow").textContent = sortAsc ? "▲" : "▼";

  // Sort rows array
  var sorted = ROWS.slice().sort(function(a,b) {{
    var va=parseNum(a[col]), vb=parseNum(b[col]);
    if (va===null&&vb===null) return 0;
    if (va===null) return 1;
    if (vb===null) return -1;
    if (typeof va==="string"&&typeof vb==="string")
      return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    return sortAsc ? va-vb : vb-va;
  }});

  // Sort ROWS (source of truth)
  ROWS.sort(function(a,b) {{
    var va=parseNum(a[col]), vb=parseNum(b[col]);
    if (va===null&&vb===null) return 0;
    if (va===null) return 1;
    if (vb===null) return -1;
    if (typeof va==="string"&&typeof vb==="string")
      return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    return sortAsc ? va-vb : vb-va;
  }});

  // Build idx→TR map từ DOM hiện tại
  var tbody = document.getElementById("tbody");
  var idxMap = {{}};
  Array.from(tbody.querySelectorAll("tr")).forEach(function(tr) {{
    idxMap[tr.dataset.idx] = tr;
  }});

  // Reorder DOM theo thứ tự ROWS mới
  ROWS.forEach(function(row, i) {{
    var tr = idxMap[row.__idx];
    if (!tr) return;
    var bg = i%2===0?"#0d1117":"#111827";
    tr.style.background = bg;
    tbody.appendChild(tr);
  }});
}}
</script>
</body>
</html>"""

    _stc.html(html, height=height, scrolling=False)





@st.cache_data(ttl=300, show_spinner=False)
def _load_all_market_data() -> tuple:
    """
    Unified loader: 1 loop duy nhất cho cả market_overview + breadth.
    Returns: (sector_df, breadth_dict, ticker_display_df)
    """
    if not PRICES_DIR.exists() or not INDUSTRY_PATH.exists():
        return pd.DataFrame(), {}, pd.DataFrame()
    try:
        from datetime import date, timedelta

        ind_df = pq.read_table(
            str(INDUSTRY_PATH), columns=["ticker","primary_industry"]
        ).to_pandas().rename(columns={"primary_industry":"industry"})
        ind_df["industry"] = ind_df["industry"].fillna("Khác")

        # Batch load company shares via PyArrow dataset
        COMPANIES_DIR = Path("data_warehouse/companies")
        shares_map = {}
        if COMPANIES_DIR.exists():
            for comp_dir in COMPANIES_DIR.glob("ticker=*"):
                tk = comp_dir.name.split("=")[1]
                ov_file = comp_dir / "overview.parquet"
                if ov_file.exists():
                    try:
                        ov = pq.ParquetFile(str(ov_file)).read(columns=["issue_share"]).to_pandas()
                        if len(ov) > 0 and pd.notna(ov["issue_share"].iloc[0]):
                            shares_map[tk] = float(ov["issue_share"].iloc[0])
                    except Exception:
                        pass

        # ── Single loop: market overview + breadth ────────────────────────────
        cutoff = pd.Timestamp(date.today() - timedelta(days=400))  # đủ cho MA200 + 52W
        rows = []
        # Breadth counters
        b_total = b_ma200 = b_rsi_ov = b_rsi_ob = 0
        b_adv = b_dec = b_unch = b_hi = b_lo = 0

        valid_tickers = set(ind_df["ticker"].tolist())

        for td in sorted(PRICES_DIR.glob("ticker=*")):
            ticker = td.name.split("=")[1]
            # Skip invalid
            if len(ticker) > 5 or not ticker.isalpha():
                continue
            try:
                frames = []
                for yd in sorted(td.glob("year=*"))[-3:]:  # 3 năm cho MA200
                    for pf in yd.glob("*.parquet"):
                        frames.append(pq.read_table(str(pf),
                            columns=["time","close","volume","high","low"]).to_pandas())
                if not frames:
                    continue
                df = pd.concat(frames).sort_values("time")
                df["time"] = pd.to_datetime(df["time"])
                df = df[df["time"] >= cutoff]
                if len(df) < 5:
                    continue

                c = df["close"].astype(float)
                v = df["volume"].astype(float)
                h = df["high"].astype(float)
                l = df["low"].astype(float)
                last = float(c.iloc[-1])

                # ── Breadth indicators (tất cả mã) ──
                b_total += 1

                # EMA 200
                if len(c) >= 200:
                    ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]
                    if last > ema200:
                        b_ma200 += 1

                # RSI 14
                delta = c.diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain / loss.replace(0, np.nan)
                rsi_val = (100 - (100 / (1 + rs))).iloc[-1]
                if not np.isnan(rsi_val):
                    if rsi_val < 30: b_rsi_ov += 1
                    elif rsi_val > 70: b_rsi_ob += 1

                # Advance / Decline
                if len(c) >= 2:
                    chg1d = c.iloc[-1] - c.iloc[-2]
                    if chg1d > 0: b_adv += 1
                    elif chg1d < 0: b_dec += 1
                    else: b_unch += 1

                # 52-week high/low
                if len(df) >= 50:
                    year_df = df.tail(252)
                    h52 = year_df["high"].astype(float).max()
                    l52 = year_df["low"].astype(float).min()
                    if last >= h52 * 0.98: b_hi += 1
                    if last <= l52 * 1.02: b_lo += 1

                # ── Market overview metrics (chỉ mã có industry) ──
                if ticker not in valid_tickers:
                    continue

                recent = df.tail(90)
                if len(recent) < 5:
                    continue
                c90 = recent["close"].astype(float)
                v90 = recent["volume"].astype(float)
                h90 = recent["high"].astype(float)
                l90 = recent["low"].astype(float)

                vol5  = float(v90.tail(5).mean())
                vol10 = float(v90.tail(10).mean())
                vol20 = float(v90.tail(20).mean())

                amp  = (h90 - l90) / c90 * 100
                amp5  = float(amp.tail(5).mean())
                amp20 = float(amp.tail(20).mean())
                amp60 = float(amp.tail(60).mean()) if len(amp) >= 60 else amp5

                chg5  = float((c90.iloc[-1]/c90.iloc[-6]-1)*100)  if len(c90)>5  else None
                chg20 = float((c90.iloc[-1]/c90.iloc[-21]-1)*100) if len(c90)>20 else None
                chg60 = float((c90.iloc[-1]/c90.iloc[-61]-1)*100) if len(c90)>60 else None

                issue_share = shares_map.get(ticker, 0)
                mktcap = last * 1000 * issue_share / 1e9 if issue_share > 0 else 0.0
                mktcap_proxy = last * 1000 * vol20 / 1e9

                rows.append({
                    "ticker": ticker, "last": last,
                    "vol5": vol5, "vol10": vol10, "vol20": vol20,
                    "mktcap": mktcap, "mktcap_proxy": mktcap_proxy,
                    "amp5": amp5, "amp20": amp20, "amp60": amp60,
                    "chg5": chg5, "chg20": chg20, "chg60": chg60,
                })
            except Exception:
                continue

        # ── Build breadth dict ────────────────────────────────────────────────
        breadth = {}
        if b_total > 0:
            breadth = {
                "total": b_total,
                "above_ma200": b_ma200,
                "above_ma200_pct": round(b_ma200 / b_total * 100, 1),
                "rsi_oversold": b_rsi_ov,
                "rsi_oversold_pct": round(b_rsi_ov / b_total * 100, 1),
                "rsi_overbought": b_rsi_ob,
                "rsi_overbought_pct": round(b_rsi_ob / b_total * 100, 1),
                "advances": b_adv, "declines": b_dec, "unchanged": b_unch,
                "ad_ratio": round(b_adv / max(b_dec, 1), 2),
                "new_highs": b_hi, "new_lows": b_lo,
                "net_new_highs": b_hi - b_lo,
            }

        if not rows:
            return pd.DataFrame(), breadth, pd.DataFrame()

        tick_df = pd.DataFrame(rows)
        merged  = tick_df.merge(ind_df, on="ticker", how="left")
        merged["industry"] = merged["industry"].fillna("Khác")

        # ── Foreign flow từ API ───────────────────────────────────────────────
        foreign_map = {}  # {ticker: {net_w, net_m, net_3m}}
        try:
            from vnstock import Vnstock
            from datetime import date as _d, timedelta as _td
            end_d   = _d.today().strftime("%Y-%m-%d")
            start_d = (_d.today() - _td(days=95)).strftime("%Y-%m-%d")

            sample_tickers = merged["ticker"].tolist()[:5]  # test với 5 mã trước
            for tk in sample_tickers:
                try:
                    ff = Vnstock().stock(symbol=tk, source="VCI").trading.foreign_trade(
                        start=start_d, end=end_d
                    )
                    if ff is not None and not ff.empty:
                        ff["time"] = pd.to_datetime(ff.get("time", ff.index))
                        # net = buy - sell value
                        for col in ff.columns:
                            cl = col.lower()
                            if "net" in cl or "ròng" in cl or "net_val" in cl:
                                net_col = col
                                break
                        else:
                            net_col = None

                        if net_col:
                            today = pd.Timestamp(_d.today())
                            net_w  = float(ff[ff["time"] >= today - _td(days=7)][net_col].sum())
                            net_m  = float(ff[ff["time"] >= today - _td(days=30)][net_col].sum())
                            net_3m = float(ff[ff["time"] >= today - _td(days=90)][net_col].sum())
                            foreign_map[tk] = {"net_w": net_w, "net_m": net_m, "net_3m": net_3m}
                except Exception:
                    continue
        except Exception:
            pass

        # ── Aggregate theo ngành ──────────────────────────────────────────────
        def agg(grp):
            n = len(grp)
            v20 = grp["vol20"].sum()
            v5  = grp["vol5"].sum()
            v10 = grp["vol10"].sum()
            total_mktcap = grp["mktcap"].sum()
            gtgd_tb = grp["mktcap_proxy"].sum()

            vol5_20  = round(v5 / v20 * 100, 0) if v20 > 0 else None

            # Foreign flow
            tickers_in = grp["ticker"].tolist()
            net_w  = sum(foreign_map.get(t, {}).get("net_w",  0) for t in tickers_in)
            net_m  = sum(foreign_map.get(t, {}).get("net_m",  0) for t in tickers_in)
            net_3m = sum(foreign_map.get(t, {}).get("net_3m", 0) for t in tickers_in)

            return pd.Series({
                "Số mã":        n,
                "Vốn hoá (tỷ)": round(total_mktcap, 0),
                "GTGD TB (tỷ)": round(gtgd_tb, 0),
                "Vol Avg 5":    round(v5  / 1e6, 1),
                "Vol Avg 10":   round(v10 / 1e6, 1),
                "Vol Avg 20":   round(v20 / 1e6, 1),
                "Vol 5/20 %":   vol5_20,
                "Biên 1T (%)":  round(grp["amp5"].mean(),  1),
                "Biên 1M (%)":  round(grp["amp20"].mean(), 1),
                "Biên 3M (%)":  round(grp["amp60"].mean(), 1),
                "Giá 1T %":     round(grp["chg5"].dropna().mean(),  1) if grp["chg5"].notna().any()  else None,
                "Giá 1M %":     round(grp["chg20"].dropna().mean(), 1) if grp["chg20"].notna().any() else None,
                "Giá 3M %":     round(grp["chg60"].dropna().mean(), 1) if grp["chg60"].notna().any() else None,
                "NN 1T (tỷ)":   round(net_w  / 1e9, 1) if net_w  != 0 else None,
                "NN 1M (tỷ)":   round(net_m  / 1e9, 1) if net_m  != 0 else None,
                "NN 3M (tỷ)":   round(net_3m / 1e9, 1) if net_3m != 0 else None,
            })

        # Ticker-level display data
        tick_display = merged.copy()
        tick_display["Vốn hoá (tỷ)"] = tick_display["mktcap"].round(0)
        tick_display["Freefloat~30% (tỷ)"] = (tick_display["mktcap"] * 0.30).round(0)
        tick_display["GTGD TB (tỷ)"] = tick_display["mktcap_proxy"].round(1)
        tick_display["Vol Avg 5"] = (tick_display["vol5"] / 1e6).round(1)
        tick_display["Vol Avg 10"] = (tick_display["vol10"] / 1e6).round(1)
        tick_display["Vol Avg 20"] = (tick_display["vol20"] / 1e6).round(1)
        tick_display["Vol 5/20 %"] = np.where(
            tick_display["vol20"] > 0,
            (tick_display["vol5"] / tick_display["vol20"] * 100).round(0),
            None
        )
        tick_display["Biên 1T (%)"] = tick_display["amp5"].round(1)
        tick_display["Biên 1M (%)"] = tick_display["amp20"].round(1)
        tick_display["Biên 3M (%)"] = tick_display["amp60"].round(1)
        tick_display["Giá 1T %"] = tick_display["chg5"].round(1)
        tick_display["Giá 1M %"] = tick_display["chg20"].round(1)
        tick_display["Giá 3M %"] = tick_display["chg60"].round(1)
        tick_display = tick_display.rename(columns={"ticker": "Mã", "industry": "Ngành"})

        result = merged.groupby("industry").apply(agg).reset_index()
        result = result.rename(columns={"industry": "Ngành"})
        result = result.sort_values("Vốn hoá (tỷ)", ascending=False).reset_index(drop=True)
        return result, breadth, tick_display

    except Exception as e:
        print(f"[_load_all_market_data] {e}")
        import traceback; traceback.print_exc()
        return pd.DataFrame(), {}, pd.DataFrame()


def load_market_overview() -> pd.DataFrame:
    """Wrapper cho backward compat."""
    mkt_df, breadth, tick_df = _load_all_market_data()
    st.session_state["_mkt_breadth"] = breadth
    st.session_state["_mkt_ticker_data"] = tick_df
    return mkt_df


def load_breadth_indicators() -> dict:
    """Wrapper — lấy từ unified cache."""
    # Trigger load nếu chưa có
    if "_mkt_breadth" not in st.session_state:
        load_market_overview()
    return st.session_state.get("_mkt_breadth", {})


@st.cache_data(ttl=300, show_spinner=False)
def load_index_overview(days: int = 30) -> pd.DataFrame:
    """
    Lấy dữ liệu chỉ số VNINDEX, VN30, HNXINDEX, HNX30 từ API.
    Trả về DataFrame pivot: mỗi dòng = 1 ngày, cột = index metrics.
    """
    try:
        from vnstock import Vnstock
        from datetime import date, timedelta

        start = (date.today() - timedelta(days=days + 15)).strftime("%Y-%m-%d")
        end = date.today().strftime("%Y-%m-%d")
        indices = ["VNINDEX", "VN30", "HNXINDEX", "HNX30"]

        def _fetch_idx(idx_name):
            try:
                stock = Vnstock().stock(symbol=idx_name, source="VCI")
                df = stock.quote.history(start=start, end=end, interval="1D")
                if df is not None and not df.empty:
                    df["time"] = pd.to_datetime(df["time"])
                    df = df.sort_values("time").tail(days)
                    df["chg_pct"] = df["close"].pct_change() * 100
                    df["gtgd"] = df["close"] * df["volume"] / 1e9
                    return idx_name, df[["time", "close", "chg_pct", "volume", "gtgd"]].copy()
            except Exception:
                pass
            return idx_name, None

        all_data = {}
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            for name, df in pool.map(lambda i: _fetch_idx(i), indices):
                if df is not None:
                    all_data[name] = df

        if not all_data:
            return pd.DataFrame()

        # Lấy danh sách ngày từ VNINDEX (chuẩn nhất)
        base = all_data.get("VNINDEX", list(all_data.values())[0])
        result = base[["time"]].copy()

        for idx, df in all_data.items():
            merged = df.rename(columns={
                "close": f"{idx}",
                "chg_pct": f"{idx}_chg",
                "gtgd": f"{idx}_gtgd",
            })
            result = result.merge(
                merged[["time", idx, f"{idx}_chg", f"{idx}_gtgd"]],
                on="time", how="left"
            )

        return result.sort_values("time", ascending=False).reset_index(drop=True)

    except Exception:
        import traceback; traceback.print_exc()
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def load_foreign_flow() -> pd.DataFrame:
    """
    Lấy dòng ngoại (foreign net flow) từ vnstock Trading API.
    Trả về DataFrame với các mã và net buy/sell value.
    """
    try:
        from vnstock import Vnstock
        from datetime import date, timedelta

        end   = date.today().strftime("%Y-%m-%d")
        start_1w  = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        start_1m  = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        start_3m  = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")

        # Lấy danh sách tất cả tickers
        if not PRICES_DIR.exists():
            return pd.DataFrame()

        import re as _re
        _CW = _re.compile(r"^C[A-Z]{2,4}\d{4}$")
        tickers = [
            p.name.replace("ticker=", "")
            for p in PRICES_DIR.iterdir()
            if p.is_dir() and p.name.startswith("ticker=")
        ][:50]  # Giới hạn 50 mã để test

        rows = []
        for ticker in tickers:
            try:
                stock = Vnstock().stock(symbol=ticker, source="VCI")
                df = stock.trading.foreign_trade()
                if df is not None and not df.empty:
                    # Tìm cột net value
                    net_cols = [c for c in df.columns if "net" in c.lower() or "ròng" in c.lower()]
                    if net_cols:
                        rows.append({
                            "ticker": ticker,
                            "net_value": float(df[net_cols[0]].iloc[0]) if len(df) > 0 else 0
                        })
            except Exception:
                continue

        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════
# Auto-refresh: detect data changes
# ═══════════════════════════════════════════════════════

def _get_data_mtime() -> float:
    """Lấy mtime mới nhất của các file data chính."""
    mtimes = []
    for p in [RESULTS_PATH, Path("data_warehouse/_meta/last_sync.json")]:
        if p.exists():
            mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else 0

_current_mtime = _get_data_mtime()
if "data_mtime" not in st.session_state:
    st.session_state["data_mtime"] = _current_mtime
elif _current_mtime > st.session_state["data_mtime"]:
    st.session_state["data_mtime"] = _current_mtime
    st.cache_data.clear()
    st.rerun()

@st.fragment(run_every=60)  # Check mỗi 60 giây
def _auto_refresh_checker():
    """Tự động detect data thay đổi và refresh."""
    mtime = _get_data_mtime()
    if mtime > st.session_state.get("data_mtime", 0):
        st.session_state["data_mtime"] = mtime
        st.cache_data.clear()
        st.rerun()

_auto_refresh_checker()

# ═══════════════════════════════════════════════════════
# Main App
# ═══════════════════════════════════════════════════════

data = load_results()

# Header
col_title, col_refresh = st.columns([6, 1])
with col_title:
    st.markdown("## 📈 VnStock Dashboard")
with col_refresh:
    if st.button("🔄 Refresh", width='stretch'):
        st.cache_data.clear()
        st.rerun()

if data is None:
    st.error("⚠️ Chưa có dữ liệu screener.\n\nChạy: `python vnstock_runner.py`")
    st.stop()

gen_time = data.get("generated_at", "—")
# Kiểm tra dữ liệu screener có cũ không
_screener_stale = False
try:
    _gen_dt = datetime.strptime(gen_time[:10], "%Y-%m-%d")
    _screener_stale = (datetime.now() - _gen_dt).days >= 1
except Exception:
    pass

_info_col, _update_col = st.columns([6, 2])
with _info_col:
    if _screener_stale:
        st.markdown(f'<p class="updated-at" style="color:#f59e0b">⚠️ Screener cũ: {gen_time} — Bấm "Cập nhật Screener" để refresh</p>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="updated-at">Cập nhật lúc: {gen_time}</p>', unsafe_allow_html=True)
with _update_col:
    _uc1, _uc2 = st.columns(2)
    with _uc1:
        if st.button("📥 Cập nhật giá", key="run_updater", use_container_width=True):
            with st.spinner("Đang cập nhật giá từ API (5-10 phút)..."):
                import subprocess
                result = subprocess.run(
                    ["python", "vnstock_updater.py", "--force"],
                    capture_output=True, text=True, cwd=str(Path(__file__).parent),
                    timeout=900,
                    env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
                )
                if result.returncode == 0:
                    st.success("Giá đã cập nhật! Đang refresh screener...")
                    # Auto-run screener after price update
                    subprocess.run(
                        ["python", "vnstock_runner.py"],
                        capture_output=True, text=True, cwd=str(Path(__file__).parent),
                        timeout=300,
                        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
                    )
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Lỗi updater: {result.stderr[:300]}")
    with _uc2:
        if st.button("🔄 Refresh Screener", key="run_screener", use_container_width=True):
            with st.spinner("Đang chạy screener (có thể mất 1-2 phút)..."):
                import subprocess
                result = subprocess.run(
                    ["python", "vnstock_runner.py"],
                    capture_output=True, text=True, cwd=str(Path(__file__).parent),
                    timeout=300,
                    env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
                )
                if result.returncode == 0:
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(f"Lỗi: {result.stderr[:500]}")

total_tickers = data.get("total_tickers", 0)
classified    = data.get("classified_tickers", 0)
presets_data  = data.get("presets", {})
total_hits    = sum(v.get("count", 0) for v in presets_data.values())
top_preset    = max(presets_data.items(), key=lambda x: x[1].get("count", 0), default=("—", {}))
industry_summary = data.get("industry_summary", {})

# ── NAVIGATION (dùng pills thay tabs để tránh lazy-render) ────────────────────
_TAB_OPTIONS = ["📊 Screener", "🔬 Phân tích", "🌏 Thị trường"]
_active_tab = st.pills("", _TAB_OPTIONS, default="📊 Screener", key="nav_tab")

# ══════════════════════════════════════════════════════
# TAB 1: SCREENER
# ══════════════════════════════════════════════════════
if _active_tab == "📊 Screener":

    # Sidebar filters (chỉ hiện khi ở tab screener)
    with st.sidebar:
        st.markdown("### 📊 Screener")
        preset_options = list(presets_data.keys())
        selected_preset = st.selectbox(
            "Preset", preset_options,
            format_func=lambda p: f"{PRESET_ICONS.get(p, '')} {p} ({presets_data[p].get('count', 0)})"
        )
        industries = ["Tất cả"] + list(industry_summary.keys())
        selected_industry = st.selectbox("Ngành", industries)
        top_n = st.slider("Hiển thị top", 10, 100, 50, step=10)

        st.divider()
        st.markdown("### ⭐ Watchlist")
        _wl_tickers = load_watchlist()
        _filter_wl = st.toggle(f"Chỉ hiện Watchlist ({len(_wl_tickers)})", key="filter_watchlist")
        _wl_add = st.text_input("Thêm mã", placeholder="VCB, FPT, ...", key="wl_add_input").upper().strip()
        _wl_c1, _wl_c2 = st.columns(2)
        with _wl_c1:
            if st.button("➕ Thêm", key="wl_add_btn", use_container_width=True) and _wl_add:
                new_tickers = [t.strip() for t in _wl_add.replace(",", " ").split() if t.strip()]
                save_watchlist(_wl_tickers + new_tickers)
                st.rerun()
        with _wl_c2:
            if st.button("🗑️ Xóa", key="wl_del_btn", use_container_width=True) and _wl_add:
                del_tickers = {t.strip() for t in _wl_add.replace(",", " ").split() if t.strip()}
                save_watchlist([t for t in _wl_tickers if t not in del_tickers])
                st.rerun()
        if _wl_tickers:
            st.caption("Đang theo dõi: " + ", ".join(_wl_tickers[:20]))
            if len(_wl_tickers) > 20:
                st.caption(f"... +{len(_wl_tickers)-20} mã khác")

        st.divider()
        st.markdown("### ⚙️ Bộ lọc nâng cao")
        price_min    = st.number_input("Giá từ (nghìn đồng)", min_value=0.0, value=0.0, step=1.0, format="%.1f")
        price_max    = st.number_input("Giá đến", min_value=0.0, value=0.0, step=1.0, format="%.1f", help="0 = không giới hạn")
        chg1d_range  = st.slider("1D%", -20.0, 20.0, (-20.0, 20.0), step=0.5, format="%.1f%%")
        chg5d_range  = st.slider("5D%", -50.0, 50.0, (-50.0, 50.0), step=1.0, format="%.1f%%")
        chg20d_range = st.slider("20D%", -80.0, 150.0, (-80.0, 150.0), step=1.0, format="%.1f%%")
        vol_min      = st.slider("Volume spike tối thiểu (×)", 0.0, 10.0, 0.0, step=0.5, format="%.1fx")

        st.divider()
        if industry_summary:
            st.markdown("### 🏭 Phân bố ngành")
            for ind, cnt in list(industry_summary.items())[:10]:
                pct = cnt / classified * 100 if classified else 0
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;font-size:12px;color:#9ca3af;margin:3px 0'>"
                    f"<span>{ind[:22]}</span><span style='color:#6ee7b7;font-family:monospace'>{cnt}</span></div>",
                    unsafe_allow_html=True
                )
                st.progress(pct / 100)

    # ── Alerts ─────────────────────────────────────────────────────────────
    _alerts = compute_alerts(gen_time)
    if _alerts:
        _new_alerts = [a for a in _alerts if a["type"] == "new"]
        _rem_alerts = [a for a in _alerts if a["type"] == "removed"]
        with st.expander(f"🔔 Alerts — {len(_new_alerts)} mã mới, {len(_rem_alerts)} mã ra ({gen_time[:10]})", expanded=False):
            _ac1, _ac2 = st.columns(2)
            with _ac1:
                if _new_alerts:
                    st.markdown("**🆕 Mới vào preset:**")
                    for a in _new_alerts[:20]:
                        icon = PRESET_ICONS.get(a["preset"], "")
                        st.markdown(f"- <span style='color:#10b981'>{a['ticker']}</span> → {icon} {a['preset']}", unsafe_allow_html=True)
                else:
                    st.caption("Không có mã mới vào preset")
            with _ac2:
                if _rem_alerts:
                    st.markdown("**❌ Ra khỏi preset:**")
                    for a in _rem_alerts[:20]:
                        icon = PRESET_ICONS.get(a["preset"], "")
                        st.markdown(f"- <span style='color:#ef4444'>{a['ticker']}</span> ← {icon} {a['preset']}", unsafe_allow_html=True)
                else:
                    st.caption("Không có mã nào ra khỏi preset")

    # Metric cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'''<div class="metric-card"><div class="label">Tổng mã theo dõi</div>
            <div class="value">{total_tickers:,}</div><div class="sub">trong warehouse</div></div>''', unsafe_allow_html=True)
    with c2:
        st.markdown(f'''<div class="metric-card"><div class="label">Đã phân loại ngành</div>
            <div class="value">{classified:,}</div><div class="sub">{classified/total_tickers*100:.0f}% tổng mã</div></div>''', unsafe_allow_html=True)
    with c3:
        st.markdown(f'''<div class="metric-card"><div class="label">Tổng tín hiệu</div>
            <div class="value">{total_hits:,}</div><div class="sub">qua {len(presets_data)} presets</div></div>''', unsafe_allow_html=True)
    with c4:
        top_count = top_preset[1].get("count", 0)
        icon = PRESET_ICONS.get(top_preset[0], "")
        st.markdown(f'''<div class="metric-card"><div class="label">Preset nhiều nhất</div>
            <div class="value">{icon} {top_count}</div><div class="sub">{top_preset[0]}</div></div>''', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if selected_preset and selected_preset in presets_data:
        preset_info = presets_data[selected_preset]
        icon = PRESET_ICONS.get(selected_preset, "📊")
        st.markdown(f"### {icon} {selected_preset.upper()}")
        st.caption(preset_info.get("desc", ""))

        df = df_from_preset(preset_info)
        if df.empty:
            st.info("Không có mã nào khớp với preset này.")
        else:
            if selected_industry != "Tất cả" and "Ngành" in df.columns:
                df = df[df["Ngành"] == selected_industry]

            raw_df = pd.DataFrame(presets_data[selected_preset]["results"])
            if not raw_df.empty and "ticker" in raw_df.columns:
                if "last_close" in raw_df.columns:
                    if price_min > 0: raw_df = raw_df[raw_df["last_close"].fillna(0) >= price_min]
                    if price_max > 0: raw_df = raw_df[raw_df["last_close"].fillna(0) <= price_max]
                if "chg_1d_pct" in raw_df.columns:
                    mask = raw_df["chg_1d_pct"].isna() | ((raw_df["chg_1d_pct"] >= chg1d_range[0]) & (raw_df["chg_1d_pct"] <= chg1d_range[1]))
                    raw_df = raw_df[mask]
                if "chg_5d_pct" in raw_df.columns:
                    mask = raw_df["chg_5d_pct"].isna() | ((raw_df["chg_5d_pct"] >= chg5d_range[0]) & (raw_df["chg_5d_pct"] <= chg5d_range[1]))
                    raw_df = raw_df[mask]
                if "chg_20d_pct" in raw_df.columns:
                    mask = raw_df["chg_20d_pct"].isna() | ((raw_df["chg_20d_pct"] >= chg20d_range[0]) & (raw_df["chg_20d_pct"] <= chg20d_range[1]))
                    raw_df = raw_df[mask]
                if vol_min > 0 and "vol_spike" in raw_df.columns:
                    raw_df = raw_df[raw_df["vol_spike"].fillna(0) >= vol_min]
                if selected_industry != "Tất cả" and "industry" in raw_df.columns:
                    raw_df = raw_df[raw_df["industry"] == selected_industry]
                filtered_tickers = set(raw_df["ticker"].tolist())
                if "Ticker" in df.columns:
                    df = df[df["Ticker"].isin(filtered_tickers)]

            # Watchlist filter
            if _filter_wl and _wl_tickers and "Ticker" in df.columns:
                df = df[df["Ticker"].isin(_wl_tickers)]

            if df.empty:
                st.info("Không có mã nào khớp với bộ lọc hiện tại.")
            else:
                st.caption(f"**{len(df)} mã** | top {min(top_n, len(df))} — Click tên cột để sắp xếp ↕ | Nhập mã vào sidebar để phân tích")
                render_table(df, top_n=top_n)

                csv = df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="⬇️ Export CSV", data=csv,
                    file_name=f"screen_{selected_preset}_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )

    st.divider()
    st.markdown("### 📊 Tổng quan tất cả presets")
    overview_data = [{"Preset": f"{PRESET_ICONS.get(p,'')} {p}", "Mô tả": v.get("desc",""), "Số mã": v.get("count",0)}
                     for p, v in presets_data.items()]
    overview_df = pd.DataFrame(overview_data).sort_values("Số mã", ascending=False)
    st.dataframe(overview_df, width='stretch', hide_index=True, height=44 + len(overview_df)*36)


# ══════════════════════════════════════════════════════
# TAB 2: PHÂN TÍCH
# ══════════════════════════════════════════════════════
if _active_tab == "🔬 Phân tích":
    # Controls cho tab phân tích
    with st.sidebar:
        st.markdown("### 🔬 Phân tích")
        ticker_input = st.text_input("Mã cổ phiếu", placeholder="VCB, FPT...", key="ticker_sidebar").upper().strip()
        if ticker_input and st.button("Phân tích →", use_container_width=True, key="anal_go"):
            st.session_state["analyze_ticker"] = ticker_input

        st.divider()
        st.markdown("### ⏱ Khoảng thời gian")
        lookback = st.select_slider(
            "Lọc từ",
            options=[0, 365, 730, 1825, 3650],
            value=0,
            format_func=lambda v: {0:"Toàn bộ lịch sử",365:"1 năm",730:"2 năm",1825:"5 năm",3650:"10 năm"}[v],
            key="lookback_anal"
        )
        load_fund = st.toggle("Tải dữ liệu cơ bản (API)", value=False, key="load_fund_anal",
                              help="Gọi vnstock API để lấy P/E, ROE, EPS...")
        st.divider()
        st.markdown("### 📐 Hiển thị chart")
        chart_height = st.slider("Chiều cao chart (px)", 500, 1400, 850, step=50, key="chart_height_anal")

        st.divider()
        st.markdown("### 🔴 Live Mode")
        if WSS_AVAILABLE:
            live_on = st.toggle(
                "Real-time WSS",
                value=st.session_state.get("live_mode", False),
                key="live_mode",
                help=f"Stream real-time cho {len(VN30_SYMBOLS)} mã VN30 + {len(INDEX_SYMBOLS)} chỉ số"
            )
            if live_on:
                _wss_client = _get_wss_singleton()
                if _wss_client is not None:
                    _wss_status = _wss_client.get_status()
                    _status_label = _wss_status.get("status", "unknown")
                    _mode_label = _wss_status.get("mode", "?")
                    _color = {
                        "connected": "#10b981",
                        "reconnecting": "#fbbf24",
                        "market_closed": "#6b7280",
                        "error": "#ef4444",
                        "disconnected": "#6b7280",
                    }.get(_status_label, "#6b7280")
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:8px;padding:6px 0">'
                        f'<span style="width:8px;height:8px;border-radius:50%;background:{_color};'
                        f'box-shadow:0 0 8px {_color}"></span>'
                        f'<span style="color:#d1d5db;font-size:12px">{_status_label.upper()}</span>'
                        f'<span style="color:#6b7280;font-size:11px">({_mode_label})</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    st.caption(f"📡 {_wss_status.get('subscribed_count', 0)} mã đã subscribe")
                    if _wss_status.get("error"):
                        st.caption(f"⚠ {_wss_status['error'][:80]}")
                else:
                    st.caption("⚠ Không khởi động được WSS client")
        else:
            st.caption("⚠ Module `vnstock_wss` chưa có — Live mode không khả dụng")

    # ── Xác định ticker cần phân tích ─────────────────────────────────────────────
    ticker = ticker_input or st.session_state.get("analyze_ticker", "")

    if not ticker:
        # Landing page
        st.markdown("## 🔬 VnStock Analysis Dashboard")
        st.markdown('<p style="color:#6b7280">Nhập mã cổ phiếu ở sidebar để bắt đầu phân tích.</p>', unsafe_allow_html=True)

        # Hiện top movers nếu có screener data
        if data and data.get("presets"):
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**⚡ Momentum mạnh nhất**")
                mom = data["presets"].get("momentum", {}).get("results", [])[:5]
                for r in mom:
                    chg = r.get("chg_20d_pct", "")
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'padding:5px 0;border-bottom:1px solid #1a2234;cursor:pointer">'
                        f'<span style="color:#60a5fa;font-weight:600">{r["ticker"]}</span>'
                        f'<span style="color:#10b981">{chg}</span></div>',
                        unsafe_allow_html=True
                    )
            with col2:
                st.markdown("**🟢 Oversold tiềm năng**")
                ov = data["presets"].get("oversold", {}).get("results", [])[:5]
                for r in ov:
                    rsi = r.get("rsi_14", "")
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'padding:5px 0;border-bottom:1px solid #1a2234">'
                        f'<span style="color:#60a5fa;font-weight:600">{r["ticker"]}</span>'
                        f'<span style="color:#fbbf24">RSI {rsi}</span></div>',
                        unsafe_allow_html=True
                    )
        st.stop()


    # ── Load data ─────────────────────────────────────────────────────────────────
    industry_map = load_industry_map()
    company_info = industry_map.get(ticker, {})

    with st.spinner(f"Đang tải dữ liệu {ticker}..."):
        df = load_price_history(ticker, days=lookback)

    if df.empty:
        st.error(f"❌ Không tìm thấy dữ liệu giá cho mã **{ticker}**. Kiểm tra lại tên mã hoặc warehouse.")
        st.stop()

    tech = get_tech_signals(df)


    # ── Header ────────────────────────────────────────────────────────────────────
    company_name = company_info.get("company_name", ticker)
    industry     = company_info.get("industry", "")
    summary      = company_info.get("business_summary", "")

    col_h1, col_h2 = st.columns([5, 1])
    with col_h1:
        st.markdown(f"## {ticker} — {company_name}")
        if industry:
            st.markdown(
                f'<span class="tag" style="background:#1e3a5f;color:#60a5fa">{industry}</span>',
                unsafe_allow_html=True
            )
        if summary and summary not in ("", "nan", "None"):
            st.caption(summary[:200] + ("..." if len(summary) > 200 else ""))
    with col_h2:
        if st.button("🔄", help="Xóa cache và tải lại"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")

    # ── Price metrics row ─────────────────────────────────────────────────────────
    price = tech.get("price", 0)
    render_metric_row([
        ("Giá hiện tại",  f"{price:,.1f}",              "nghìn đồng"),
        ("1 ngày",        fmt_pct(tech.get("chg1d")),   f"{df['time'].iloc[-1].strftime('%d/%m/%Y')}"),
        ("5 ngày",        fmt_pct(tech.get("chg5d")),   "so với 5 phiên trước"),
        ("20 ngày",       fmt_pct(tech.get("chg20d")),  "so với 20 phiên trước"),
        ("52W Range",     f"{tech.get('pct52', 0):.0f}%", f"Low {tech.get('lo52',0):,.1f} — High {tech.get('hi52',0):,.1f}"),
    ])

    # ── Chart ─────────────────────────────────────────────────────────────────────
    # ── Timeframe selector ──────────────────────────────────────────────
    tf_options = ["1m","5m","15m","30m","1H","1D","1W","1M","All"]
    if "tf" not in st.session_state:
        st.session_state["tf"] = "1D"
    tf_cols = st.columns(len(tf_options) + 2)
    for _i, _val in enumerate(tf_options):
        with tf_cols[_i]:
            _active = st.session_state["tf"] == _val
            if st.button(_val, key=f"tf_{_val}",
                         type="primary" if _active else "secondary",
                         use_container_width=True):
                st.session_state["tf"] = _val
                st.cache_data.clear()
                st.rerun()
    tf = st.session_state["tf"]

    if tf in ("1m","5m","15m","30m","1H"):
        with st.spinner(f"Đang tải {tf} data từ VCI..."):
            chart_df = load_intraday(ticker, interval=tf)
        if chart_df.empty:
            st.warning(f"Không lấy được dữ liệu {tf}. Hiển thị daily.")
            chart_df = df
    elif tf == "1W":
        # Resample từ daily warehouse (stable hơn API 1W)
        chart_df = resample_ohlcv(df, "W")
    elif tf == "1M":
        chart_df = resample_ohlcv(df, "ME")
    else:
        chart_df = df

    # ── Live mode: wrap chart + quote strip trong fragment auto-refresh ─────────
    _live_on = st.session_state.get("live_mode", False) and WSS_AVAILABLE and tf in ("1m","5m","15m","30m","1H")

    if _live_on:
        # Banner nhắc nhở Live mode đang hoạt động
        st.markdown(
            '<div style="background:linear-gradient(90deg,#ef4444,#f59e0b);'
            'padding:6px 14px;border-radius:6px;margin:8px 0;'
            'display:flex;align-items:center;gap:10px;font-weight:500">'
            '<span style="width:10px;height:10px;border-radius:50%;background:#fff;'
            'box-shadow:0 0 10px #fff;animation:pulse 1.5s infinite"></span>'
            f'<span style="color:#fff;font-size:13px">🔴 LIVE MODE — {ticker} @ {tf} — refresh 3s</span>'
            '</div>',
            unsafe_allow_html=True
        )

        @st.fragment(run_every=3)
        def _live_intraday_fragment():
            live_q = load_live_quote(ticker)
            _chart_df = load_intraday(ticker, interval=tf)

            # Quote strip — HIỂN THỊ TRƯỚC chart để luôn visible
            if live_q:
                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                _price = float(live_q.get("price", 0))
                _chg = float(live_q.get("chg_pct", 0))
                _vol = float(live_q.get("volume", 0))
                _bid = float(live_q.get("bid", 0))
                _ask = float(live_q.get("ask", 0))
                # Normalize hiển thị theo scale của historical chart
                _display_price = _price
                _scale = 1.0
                if not _chart_df.empty:
                    _last_close = float(_chart_df.iloc[-1]["close"])
                    _display_price = _normalize_live_price(_last_close, _price)
                    _bid_disp = _normalize_live_price(_last_close, _bid) if _bid else 0
                    _ask_disp = _normalize_live_price(_last_close, _ask) if _ask else 0
                    if _display_price > 0 and _price > 0:
                        _scale = _price / _display_price
                else:
                    _bid_disp, _ask_disp = _bid, _ask
                lc1.metric("💰 Giá Live", f"{_display_price:,.2f}", f"{_chg:+.2f}%")
                lc2.metric("📊 Volume tích luỹ", f"{_vol:,.0f}",
                           help="Tổng khối lượng khớp từ đầu phiên 9:00 tới hiện tại")
                lc3.metric("🟢 Bid (tốt nhất)", f"{_bid_disp:,.2f}" if _bid else "—")
                lc4.metric("🔴 Ask (tốt nhất)", f"{_ask_disp:,.2f}" if _ask else "—")
                lc5.metric("⏱ Cập nhật", str(live_q.get("time", ""))[-8:])

                # Order book — 3 mức cho stock, 10 mức cho futures
                _bids = live_q.get("bids", [])
                _asks = live_q.get("asks", [])
                if _bids or _asks:
                    _is_fut = is_futures(ticker) or live_q.get("type") == "futures"
                    _max_lv = 10 if _is_fut else 3
                    _title = (
                        f"📋 Sổ lệnh ({_max_lv} mức) — "
                        f"{'Hợp đồng tương lai' if _is_fut else 'Cổ phiếu'}"
                    )
                    render_order_book(
                        _bids, _asks,
                        scale=_scale,
                        max_levels=_max_lv,
                        title=_title,
                    )
            else:
                _allowed = VN30_SYMBOLS + INDEX_SYMBOLS + FUTURES_SYMBOLS
                st.warning(
                    f"⏳ Chưa có dữ liệu live cho {ticker}. "
                    + ("(Ngoài VN30/Index/Futures — chỉ VN30+Index+VN30F mới được stream)"
                       if ticker not in _allowed
                       else "Chờ WSS kết nối...")
                )

            # Merge live vào chart nếu có cùng scale
            if live_q and not _chart_df.empty:
                _chart_df = _merge_live_quote(_chart_df, live_q)

            try:
                render_chart(_chart_df, ticker, height=st.session_state.get("chart_height_anal", 850))
            except Exception as _e:
                st.error(f"Chart render error: {_e}")

        _live_intraday_fragment()
    else:
        render_chart(chart_df, ticker, height=st.session_state.get("chart_height_anal", 850))

    st.markdown("---")

    # ── Technical + Fundamental side by side ─────────────────────────────────────
    col_tech, col_fund = st.columns([1, 1])

    with col_tech:
        st.markdown('<p class="section-title">📈 Phân tích kỹ thuật</p>', unsafe_allow_html=True)

        # RSI gauge
        rsi = tech.get("rsi")
        if rsi:
            rsi_color = "#10b981" if rsi < 30 else ("#ef4444" if rsi > 70 else "#fbbf24")
            st.markdown(
                f'<div class="card">'
                f'<div class="card-title">RSI (14)</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:32px;'
                f'font-weight:500;color:{rsi_color}">{rsi:.1f}</div>'
                f'<div class="fscore-bar"><div class="fscore-fill" style="width:{rsi}%;background:{rsi_color}"></div></div>'
                f'<div style="font-size:11px;color:#6b7280;display:flex;justify-content:space-between">'
                f'<span>Oversold &lt;30</span><span>Overbought &gt;70</span></div>'
                f'</div>',
                unsafe_allow_html=True
            )

        # Signals
        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_signal_badge("RSI Signal",  tech.get("rsi_sig",  "NEUTRAL"))
        render_signal_badge("MACD Signal", tech.get("macd_sig", "NEUTRAL"))
        render_signal_badge("EMA Trend",   tech.get("ema_sig",  "NEUTRAL"))
        render_signal_badge("BB Signal",   tech.get("bb_sig",   "NEUTRAL"))
        st.markdown('</div>', unsafe_allow_html=True)

        # EMA levels
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">EMA Levels</div>', unsafe_allow_html=True)
        for span, val in [("EMA 9", tech.get("ema9")), ("EMA 21", tech.get("ema21")),
                           ("EMA 50", tech.get("ema50")), ("EMA 200", tech.get("ema200"))]:
            if val:
                diff = round((price - val) / val * 100, 2)
                color = "#10b981" if price > val else "#ef4444"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:5px 0;border-bottom:1px solid #1a2234;font-size:13px">'
                    f'<span style="color:#9ca3af">{span}</span>'
                    f'<span style="color:#e5e7eb">{val:,.2f}</span>'
                    f'<span style="color:{color}">{fmt_pct(diff)}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        st.markdown('</div>', unsafe_allow_html=True)

        # Volume
        vol = tech.get("vol")
        vol_ma = tech.get("vol_ma20")
        vol_spike = tech.get("vol_spike")
        if vol and vol_ma:
            spike_color = "#f97316" if vol_spike and vol_spike > 2 else "#9ca3af"
            st.markdown(
                f'<div class="card">'
                f'<div class="card-title">Volume</div>'
                f'<div style="font-size:16px;color:#e5e7eb">{vol/1e6:.1f}M</div>'
                f'<div style="font-size:12px;color:{spike_color};margin-top:4px">'
                f'Vol spike: {vol_spike:.1f}× MA20</div>'
                f'</div>',
                unsafe_allow_html=True
            )

        # Tech score
        ts = tech.get("tech_score", 0)
        ts_color = "#10b981" if ts > 0.2 else ("#ef4444" if ts < -0.2 else "#fbbf24")
        ts_label = "BULLISH" if ts > 0.2 else ("BEARISH" if ts < -0.2 else "NEUTRAL")
        st.markdown(
            f'<div class="card">'
            f'<div class="card-title">Technical Score</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:28px;color:{ts_color}">'
            f'{ts:+.2f}</div>'
            f'<div style="font-size:12px;color:{ts_color};font-weight:600">{ts_label}</div>'
            f'</div>',
            unsafe_allow_html=True
        )


    with col_fund:
        st.markdown('<p class="section-title">🏦 Phân tích cơ bản</p>', unsafe_allow_html=True)

        if load_fund:
            with st.spinner("Đang tải dữ liệu cơ bản từ API..."):
                fund = load_fundamental(ticker)

            # Debug: show raw result
            if fund:
                non_none = {k:v for k,v in fund.items() if v is not None}
                if not non_none or (len(non_none)==1 and "error" in non_none):
                    st.warning(f"⚠ Không lấy được dữ liệu cơ bản. Raw: {fund}")
                elif fund.get("error"):
                    st.warning(f"Lỗi: {fund['error']}")
            else:
                st.warning("⚠ load_fundamental() trả về rỗng")

            if fund.get("error"):
                pass  # already shown above
            elif fund:
                # Key ratios
                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown('<div class="card-title">Định giá & Sinh lời</div>', unsafe_allow_html=True)
                ratios = [
                    ("P/E",            fund.get("pe"),    "lần"),
                    ("P/B",            fund.get("pb"),    "lần"),
                    ("ROE",            fund.get("roe"),   "%"),
                    ("ROA",            fund.get("roa"),   "%"),
                    ("EPS",            fund.get("eps"),   "VND"),
                    ("Biên LN gộp",   fund.get("gross_margin"), "%"),
                    ("Biên LN ròng",  fund.get("net_margin"),   "%"),
                    ("Tỷ lệ nợ",      fund.get("debt_ratio"),   ""),
                    ("Tăng trưởng DT", fund.get("revenue_growth"), "%"),
                ]
                for label, val, unit in ratios:
                    if val is not None:
                        color = "#e5e7eb"
                        if label in ("ROE","ROA") and val > 15: color = "#10b981"
                        if label == "Tăng trưởng DT":
                            color = "#10b981" if val > 0 else "#ef4444"
                        if label == "P/E" and val < 15: color = "#10b981"
                        if label == "P/E" and val > 30: color = "#ef4444"
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;'
                            f'padding:6px 0;border-bottom:1px solid #1a2234;font-size:13px">'
                            f'<span style="color:#9ca3af">{label}</span>'
                            f'<span style="color:{color};font-family:IBM Plex Mono,monospace">'
                            f'{val:.2f} {unit}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                st.markdown('</div>', unsafe_allow_html=True)

            # Fund score từ ratios
            fund_score = None
            if not fund.get("error"):
                pts = 0; cnt = 0
                if fund.get("roe") and fund["roe"] > 15:   pts += 1; cnt += 1
                elif fund.get("roe"):                        cnt += 1
                if fund.get("roa") and fund["roa"] > 5:    pts += 1; cnt += 1
                elif fund.get("roa"):                        cnt += 1
                if fund.get("pe") and 0 < fund["pe"] < 20: pts += 1; cnt += 1
                elif fund.get("pe"):                         cnt += 1
                if fund.get("revenue_growth") and fund["revenue_growth"] > 0: pts += 1; cnt += 1
                elif fund.get("revenue_growth") is not None: cnt += 1
                if fund.get("net_margin") and fund["net_margin"] > 10: pts += 1; cnt += 1
                elif fund.get("net_margin"):                  cnt += 1

                if cnt > 0:
                    fund_score = round((pts / cnt) * 2 - 1, 2)
                    fs_color = "#10b981" if fund_score > 0.2 else ("#ef4444" if fund_score < -0.2 else "#fbbf24")
                    fs_label = "STRONG" if fund_score > 0.5 else ("GOOD" if fund_score > 0.2 else ("WEAK" if fund_score < -0.2 else "FAIR"))
                    st.markdown(
                        f'<div class="card">'
                        f'<div class="card-title">Fundamental Score</div>'
                        f'<div style="font-family:IBM Plex Mono,monospace;font-size:28px;color:{fs_color}">'
                        f'{fund_score:+.2f}</div>'
                        f'<div style="font-size:12px;color:{fs_color};font-weight:600">{fs_label} ({pts}/{cnt} tiêu chí)</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

        else:
            st.markdown(
                '<div class="card" style="border:1px dashed #374151">'
                '<div class="card-title">Dữ liệu cơ bản</div>'
                '<div style="color:#6b7280;font-size:13px;line-height:1.7">'
                'Bật toggle <strong style="color:#9ca3af">Tải dữ liệu cơ bản</strong> ở sidebar '
                'để xem P/E, ROE, EPS và các chỉ số tài chính khác.'
                '</div></div>',
                unsafe_allow_html=True
            )

        # Consensus
        ts = tech.get("tech_score", 0)
        fund_score_val = fund_score if load_fund and not fund.get("error") and fund_score is not None else 0
        weight_t, weight_f = (0.5, 0.5) if not load_fund else (0.4, 0.6)
        composite = round(ts * weight_t + fund_score_val * weight_f, 2)

        rec_label = (
            "STRONG BUY 🟢🟢" if composite > 0.6 else
            "BUY 🟢"          if composite > 0.2 else
            "HOLD 🟡"         if composite >= -0.2 else
            "SELL 🔴"         if composite >= -0.6 else
            "STRONG SELL 🔴🔴"
        )
        rec_color = "#10b981" if composite > 0.2 else ("#ef4444" if composite < -0.2 else "#fbbf24")

        st.markdown(
            f'<div class="card" style="border:1px solid {rec_color}40;margin-top:12px">'
            f'<div class="card-title">Khuyến nghị tổng hợp'
            f'{"(40% tech + 60% fund)" if load_fund else "(chỉ technical)"}'
            f'</div>'
            f'<div style="font-size:24px;font-weight:600;color:{rec_color};margin:8px 0">'
            f'{rec_label}</div>'
            f'<div style="font-size:12px;color:#6b7280">'
            f'Composite score: <span style="color:{rec_color};font-family:IBM Plex Mono">'
            f'{composite:+.2f}</span></div>'
            f'</div>',
            unsafe_allow_html=True
        )

# ══════════════════════════════════════════════════════
# TAB 3: THỊ TRƯỜNG
# ══════════════════════════════════════════════════════
if _active_tab == "🌏 Thị trường":
    col_title_m, col_ref_m = st.columns([6,1])
    with col_title_m:
        st.markdown("### 🌏 Tổng quan thị trường theo ngành")
    with col_ref_m:
        if st.button("🔄", key="market_refresh", help="Refresh"):
            st.cache_data.clear()
            st.rerun()

    # ── Chỉ số thị trường ────────────────────────────────────────────────────
    with st.spinner("Đang tải dữ liệu chỉ số..."):
        idx_df = load_index_overview(days=30)

    if not idx_df.empty:
        st.markdown("#### 📈 Diễn biến chỉ số thị trường (30 phiên)")
        _indices = ["VNINDEX", "VN30", "HNXINDEX", "HNX30"]
        _idx_avail = [i for i in _indices if i in idx_df.columns]

        # Tính min/max GTGD toàn bảng cho data bar scale
        _gtgd_cols = [f"{i}_gtgd" for i in _idx_avail if f"{i}_gtgd" in idx_df.columns]
        _all_gtgd = []
        for gc in _gtgd_cols:
            _all_gtgd.extend(idx_df[gc].dropna().abs().tolist())
        _gtgd_max = max(_all_gtgd) if _all_gtgd else 1

        # Build HTML table
        _th = ("background:#111827;color:#6b7280;font-size:10px;font-weight:500;"
               "text-transform:uppercase;letter-spacing:0.05em;padding:6px 8px;"
               "border-bottom:2px solid #1f2937;white-space:nowrap;text-align:center;"
               "font-family:'IBM Plex Sans',sans-serif;")
        _td = "padding:5px 8px;border-bottom:1px solid #1a2234;white-space:nowrap;font-size:11px;font-family:'IBM Plex Mono',monospace;"

        # Headers: Date | VNINDEX close %D GTGD | VN30 close %D GTGD | ...
        header_html = f'<th style="{_th}">Ngày</th>'
        for idx_name in _idx_avail:
            header_html += f'<th colspan="3" style="{_th};border-left:2px solid #1f2937">{idx_name}</th>'

        sub_header = f'<th style="{_th}"></th>'
        for _ in _idx_avail:
            sub_header += f'<th style="{_th};border-left:2px solid #1f2937;font-size:9px">Close</th>'
            sub_header += f'<th style="{_th};font-size:9px">%D</th>'
            sub_header += f'<th style="{_th};font-size:9px">GTGD (tỷ)</th>'

        rows_idx = []
        for i, (_, row) in enumerate(idx_df.head(20).iterrows()):
            bg = "#0d1117" if i % 2 == 0 else "#111827"
            date_str = pd.Timestamp(row["time"]).strftime("%Y-%m-%d")
            cells = f'<td style="{_td}color:#9ca3af">{date_str}</td>'

            for idx_name in _idx_avail:
                close_val = row.get(idx_name)
                chg_val = row.get(f"{idx_name}_chg")
                gtgd_val = row.get(f"{idx_name}_gtgd")

                # Close
                close_str = f"{close_val:,.2f}" if pd.notna(close_val) else "—"
                cells += f'<td style="{_td}color:#e5e7eb;text-align:right;border-left:2px solid #1f2937">{close_str}</td>'

                # %D with color
                if pd.notna(chg_val):
                    chg_color = "#10b981" if chg_val > 0 else ("#ef4444" if chg_val < 0 else "#9ca3af")
                    chg_str = f"+{chg_val:.1f}%" if chg_val > 0 else f"{chg_val:.1f}%"
                    cells += f'<td style="{_td}color:{chg_color};text-align:right">{chg_str}</td>'
                else:
                    cells += f'<td style="{_td}color:#4b5563;text-align:right">—</td>'

                # GTGD data bar
                if pd.notna(gtgd_val):
                    bar_pct = min(100, int(abs(gtgd_val) / _gtgd_max * 100))
                    bar_color = "#10b981" if pd.notna(chg_val) and chg_val >= 0 else "#ef4444"
                    gtgd_str = f"{gtgd_val:,.0f}"
                    cells += (
                        f'<td style="{_td}padding:3px 6px;min-width:100px">'
                        f'<div style="display:flex;align-items:center;gap:4px;justify-content:flex-end">'
                        f'<span style="color:#6b7280;font-size:10px">{gtgd_str}</span>'
                        f'<div style="width:50px;height:12px;background:#1a2234;border-radius:2px;overflow:hidden">'
                        f'<div style="width:{bar_pct}%;height:100%;background:{bar_color};border-radius:2px"></div>'
                        f'</div></div></td>'
                    )
                else:
                    cells += f'<td style="{_td}color:#4b5563;text-align:right">—</td>'

            rows_idx.append(f'<tr style="background:{bg}">{cells}</tr>')

        idx_tbl = f"""<div style="overflow-x:auto;border-radius:8px;border:1px solid #1f2937;background:#0d1117;max-height:500px;overflow-y:auto">
<table style="width:100%;border-collapse:collapse">
<thead><tr>{header_html}</tr><tr>{sub_header}</tr></thead>
<tbody>{"".join(rows_idx)}</tbody>
</table></div>"""
        st.markdown(idx_tbl, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Load tất cả dữ liệu thị trường (1 lần duy nhất) ─────────────────────
    with st.spinner("Đang tổng hợp dữ liệu thị trường..."):
        mkt_df = load_market_overview()
    breadth = st.session_state.get("_mkt_breadth", {})

    if breadth:
        st.markdown("#### 📊 Breadth Indicators — Sức khỏe thị trường")
        b1, b2, b3, b4, b5 = st.columns(5)

        pct_ma200 = breadth["above_ma200_pct"]
        ma200_color = "#10b981" if pct_ma200 > 50 else ("#f59e0b" if pct_ma200 > 30 else "#ef4444")
        with b1:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">Trên MA200</div>'
                f'<div class="value" style="color:{ma200_color}">{pct_ma200:.1f}%</div>'
                f'<div class="sub">{breadth["above_ma200"]}/{breadth["total"]} mã</div>'
                f'</div>', unsafe_allow_html=True)

        with b2:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">RSI &lt; 30 (Quá bán)</div>'
                f'<div class="value" style="color:#10b981">{breadth["rsi_oversold_pct"]:.1f}%</div>'
                f'<div class="sub">{breadth["rsi_oversold"]} mã oversold</div>'
                f'</div>', unsafe_allow_html=True)

        with b3:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">RSI &gt; 70 (Quá mua)</div>'
                f'<div class="value" style="color:#ef4444">{breadth["rsi_overbought_pct"]:.1f}%</div>'
                f'<div class="sub">{breadth["rsi_overbought"]} mã overbought</div>'
                f'</div>', unsafe_allow_html=True)

        ad = breadth["ad_ratio"]
        ad_color = "#10b981" if ad > 1 else ("#ef4444" if ad < 1 else "#9ca3af")
        with b4:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">A/D Ratio</div>'
                f'<div class="value" style="color:{ad_color}">{ad:.2f}</div>'
                f'<div class="sub">↑{breadth["advances"]} ↓{breadth["declines"]} ={breadth["unchanged"]}</div>'
                f'</div>', unsafe_allow_html=True)

        nnh = breadth["net_new_highs"]
        nnh_color = "#10b981" if nnh > 0 else ("#ef4444" if nnh < 0 else "#9ca3af")
        with b5:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">Net New Highs</div>'
                f'<div class="value" style="color:{nnh_color}">{nnh:+d}</div>'
                f'<div class="sub">↑{breadth["new_highs"]} đỉnh · ↓{breadth["new_lows"]} đáy 52W</div>'
                f'</div>', unsafe_allow_html=True)

        # ── Progress bars ─────────────────────────────────────────────────────
        pb1, pb2, pb3 = st.columns(3)
        with pb1:
            st.caption("% Trên MA200")
            st.progress(min(pct_ma200 / 100, 1.0))
        with pb2:
            adv_pct = breadth["advances"] / max(breadth["total"], 1)
            st.caption(f"Advance/Decline ({breadth['advances']}/{breadth['declines']})")
            st.progress(min(adv_pct, 1.0))
        with pb3:
            rsi_neutral = 100 - breadth["rsi_oversold_pct"] - breadth["rsi_overbought_pct"]
            st.caption(f"RSI: 🟢{breadth['rsi_oversold_pct']:.0f}% · ⚪{rsi_neutral:.0f}% · 🔴{breadth['rsi_overbought_pct']:.0f}%")
            st.progress(min(rsi_neutral / 100, 1.0))

        st.divider()

    # ── Market Overview theo ngành (dữ liệu đã load ở trên) ─────────────────
    if mkt_df.empty:
        st.warning("Không có dữ liệu.")
    else:
        # ── Metric cards ───────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        total_sectors = len(mkt_df)
        total_mktcap  = mkt_df["Vốn hoá (tỷ)"].sum() if "Vốn hoá (tỷ)" in mkt_df.columns else 0
        total_vol20   = mkt_df["Vol Avg 20"].sum()
        top_sector    = str(mkt_df.iloc[0]["Ngành"])

        with c1:
            st.markdown(f'<div class="metric-card"><div class="label">Số ngành</div><div class="value">{total_sectors}</div><div class="sub">đã phân loại</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><div class="label">Tổng vốn hoá</div><div class="value">{total_mktcap/1000:,.0f} nghìn tỷ</div><div class="sub">VND</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card"><div class="label">KLGD TB 20 ngày</div><div class="value">{total_vol20:,.0f}M</div><div class="sub">triệu cổ phiếu</div></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="metric-card"><div class="label">Ngành KLGD cao nhất</div><div class="value">{top_sector[:14]}</div><div class="sub">Vol 20: {float(mkt_df.iloc[0]["Vol Avg 20"]):.0f}M cp</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Drill-down + Sort controls ────────────────────────────────────────
        _ctrl1, _ctrl2, _ctrl3 = st.columns([4, 2, 1])
        _nganh_list = ["Tổng quan theo ngành"] + mkt_df["Ngành"].tolist()
        with _ctrl1:
            _selected_nganh = st.selectbox(
                "Ngành", _nganh_list, key="mkt_drill_industry",
                label_visibility="collapsed",
                placeholder="🔍 Click chọn ngành để drill-down..."
            )
        _sort_cols = ["Vốn hoá (tỷ)","GTGD TB (tỷ)","Vol Avg 20","Vol 5/20 %",
                      "Biên 1T (%)","Biên 1M (%)","Biên 3M (%)",
                      "Giá 1T %","Giá 1M %","Giá 3M %"]
        with _ctrl2:
            _sort_by = st.selectbox("Sắp xếp", _sort_cols, key="mkt_sort_col", label_visibility="collapsed")
        with _ctrl3:
            _sort_dir = st.selectbox("↕", ["↓ Giảm","↑ Tăng"], key="mkt_sort_dir", label_visibility="collapsed")
        _sort_asc = (_sort_dir == "↑ Tăng")

        # ── Bảng tổng hợp (ẩn khi drill-down) ─────────────────────────────────
        has_foreign = mkt_df["NN 1T (tỷ)"].notna().any()
        _show_sector_table = (_selected_nganh == "Tổng quan theo ngành")

        # ── Color scale cho Biên độ (tương quan giữa ngành + khung thời gian) ──
        _amp_cols = ["Biên 1T (%)","Biên 1M (%)","Biên 3M (%)"]
        _amp_all_vals = []
        for _ac in _amp_cols:
            if _ac in mkt_df.columns:
                _amp_all_vals.extend(mkt_df[_ac].dropna().tolist())
        _amp_min = min(_amp_all_vals) if _amp_all_vals else 0
        _amp_max = max(_amp_all_vals) if _amp_all_vals else 1
        _amp_range = _amp_max - _amp_min if _amp_max > _amp_min else 1

        def _amp_color(val):
            """Map biên độ → gradient xanh lá (thấp) → vàng (TB) → đỏ (cao)."""
            t = (float(val) - _amp_min) / _amp_range  # 0..1
            t = max(0, min(1, t))
            if t < 0.5:
                # xanh lá → vàng
                r = int(16 + (245 - 16) * (t / 0.5))
                g = int(185 + (158 - 185) * (t / 0.5))
                b = int(129 + (11 - 129) * (t / 0.5))
            else:
                # vàng → đỏ
                r = int(245 + (239 - 245) * ((t - 0.5) / 0.5))
                g = int(158 + (68 - 158) * ((t - 0.5) / 0.5))
                b = int(11 + (68 - 11) * ((t - 0.5) / 0.5))
            return f"rgb({r},{g},{b})"

        def color_val(val, col):
            """Trả về màu CSS theo giá trị."""
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return "#4b5563"
            if col in ("Giá 1T %","Giá 1M %","Giá 3M %","NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)"):
                return "#10b981" if float(val) > 0 else ("#ef4444" if float(val) < 0 else "#9ca3af")
            if col == "Vol 5/20 %":
                v = float(val)
                return "#10b981" if v > 110 else ("#ef4444" if v < 90 else "#e5e7eb")
            if col in _amp_cols:
                return _amp_color(val)
            return "#e5e7eb"

        def fmt(val, col):
            if val is None:
                return "—"
            if isinstance(val, str):
                return val  # cột text như Ngành — trả về nguyên
            try:
                if np.isnan(float(val)):
                    return "—"
            except Exception:
                return str(val)
            v = float(val)
            if col in ("Giá 1T %","Giá 1M %","Giá 3M %"):
                return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
            if col in ("NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)"):
                return f"+{v:,.1f}" if v > 0 else f"{v:,.1f}"
            if col in ("Vol Avg 5","Vol Avg 10","Vol Avg 20"):
                return f"{v:,.1f}M"
            if col == "Vol 5/20 %":
                return f"{v:.0f}%"
            if col in ("Vốn hoá (tỷ)","GTGD TB (tỷ)","Freefloat~30% (tỷ)","Freefloat (tỷ)"):
                return f"{v:,.0f}"
            if col in ("Biên 1T (%)","Biên 1M (%)","Biên 3M (%)"):
                return f"{v:.1f}%"
            return str(int(v)) if v == int(v) else f"{v:.1f}"

        # Chọn cột hiển thị
        display_cols = ["Ngành","Số mã","Vốn hoá (tỷ)","Freefloat~30% (tỷ)","GTGD TB (tỷ)",
                        "Vol Avg 5","Vol Avg 10","Vol Avg 20","Vol 5/20 %",
                        "Biên 1T (%)","Biên 1M (%)","Biên 3M (%)",
                        "Giá 1T %","Giá 1M %","Giá 3M %"]
        if has_foreign:
            display_cols += ["NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)"]

        avail_cols = [c for c in display_cols if c in mkt_df.columns]

        # Build shared styles
        th_style = ("background:#111827;color:#6b7280;font-size:10px;font-weight:500;"
                    "text-transform:uppercase;letter-spacing:0.05em;padding:8px 10px;"
                    "border-bottom:2px solid #1f2937;white-space:nowrap;font-family:'IBM Plex Sans',sans-serif;")
        td_base   = "padding:7px 10px;border-bottom:1px solid #1a2234;white-space:nowrap;font-size:12px;font-family:'IBM Plex Mono',monospace;"

        if _show_sector_table:
            # ── Bảng ngành (sorted) ───────────────────────────────────────────
            if _sort_by in mkt_df.columns:
                mkt_df = mkt_df.sort_values(_sort_by, ascending=_sort_asc, na_position="last").reset_index(drop=True)
            rows_html = []
            for i, (_, row) in enumerate(mkt_df.iterrows()):
                bg = "#0d1117" if i%2==0 else "#111827"
                cells = []
                for col in avail_cols:
                    val = row.get(col)
                    display = fmt(val, col)
                    color   = color_val(val, col)
                    if col == "Ngành":
                        cells.append(f'<td style="{td_base}color:#a78bfa;font-weight:600;font-family:IBM Plex Sans,sans-serif">{display}</td>')
                    elif col == "Số mã":
                        cells.append(f'<td style="{td_base}color:#6b7280;text-align:center">{display}</td>')
                    elif col in _amp_cols and val is not None and not (isinstance(val, float) and np.isnan(val)):
                        t = (float(val) - _amp_min) / _amp_range
                        t = max(0, min(1, t))
                        bar_w = max(4, int(t * 100))
                        bar_color = _amp_color(val)
                        cells.append(
                            f'<td style="{td_base}padding:4px 6px;min-width:90px">'
                            f'<div style="display:flex;align-items:center;gap:5px;justify-content:flex-end">'
                            f'<span style="color:#9ca3af;font-size:11px">{display}</span>'
                            f'<div style="width:60px;height:14px;background:#1a2234;border-radius:2px;overflow:hidden">'
                            f'<div style="width:{bar_w}%;height:100%;background:{bar_color};border-radius:2px"></div>'
                            f'</div></div></td>')
                    else:
                        align = "right" if col != "Ngành" else "left"
                        cells.append(f'<td style="{td_base}color:{color};text-align:{align}">{display}</td>')
                rows_html.append(f'<tr style="background:{bg}">' + "".join(cells) + "</tr>")

            headers = "".join(f'<th style="{th_style}">{c}</th>' for c in avail_cols)
            tbl_height = min(700, 52 + len(mkt_df)*36)
            html_tbl = f"""<div style="overflow-x:auto;border-radius:8px;border:1px solid #1f2937;background:#0d1117;max-height:{tbl_height}px;overflow-y:auto">
<table style="width:100%;border-collapse:collapse">
<thead><tr>{headers}</tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table></div>"""

            st.markdown(html_tbl, unsafe_allow_html=True)

            csv = mkt_df[avail_cols].to_csv(index=False, encoding="utf-8-sig")
            st.download_button("⬇️ Export CSV", data=csv,
                               file_name=f"market_overview_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                               mime="text/csv")

            if not has_foreign:
                st.caption("⚠️ Dữ liệu dòng ngoại (NN) chưa có — cần vnstock API `Trading.foreign_trade()`. "
                           "Vốn hoá và Freefloat là ước tính proxy từ giá × khối lượng.")

        # ── Drill-down: chi tiết công ty theo ngành ───────────────────────────
        if _selected_nganh != "Tổng quan theo ngành":
            tick_data = st.session_state.get("_mkt_ticker_data")
            if tick_data is not None and not tick_data.empty:
                sector_df = tick_data[tick_data["Ngành"] == _selected_nganh].copy()
                if not sector_df.empty:
                    if _sort_by in sector_df.columns:
                        sector_df = sector_df.sort_values(_sort_by, ascending=_sort_asc, na_position="last")
                    else:
                        sector_df = sector_df.sort_values("Vốn hoá (tỷ)", ascending=False)
                    st.markdown(f"#### 🏢 Chi tiết ngành: {_selected_nganh} ({len(sector_df)} mã)")

                    # Reuse table rendering logic
                    _dd_cols = ["Mã","Vốn hoá (tỷ)","Freefloat~30% (tỷ)","GTGD TB (tỷ)",
                                "Vol Avg 5","Vol Avg 10","Vol Avg 20","Vol 5/20 %",
                                "Biên 1T (%)","Biên 1M (%)","Biên 3M (%)",
                                "Giá 1T %","Giá 1M %","Giá 3M %"]
                    _dd_avail = [c for c in _dd_cols if c in sector_df.columns]

                    # Amp scale cho drill-down
                    _dd_amp_vals = []
                    for _ac in _amp_cols:
                        if _ac in sector_df.columns:
                            _dd_amp_vals.extend(sector_df[_ac].dropna().tolist())
                    _dd_amp_min = min(_dd_amp_vals) if _dd_amp_vals else 0
                    _dd_amp_max = max(_dd_amp_vals) if _dd_amp_vals else 1
                    _dd_amp_rng = _dd_amp_max - _dd_amp_min if _dd_amp_max > _dd_amp_min else 1

                    def _dd_amp_color(val):
                        t = max(0, min(1, (float(val) - _dd_amp_min) / _dd_amp_rng))
                        if t < 0.5:
                            r = int(16 + (245 - 16) * (t / 0.5))
                            g = int(185 + (158 - 185) * (t / 0.5))
                            b = int(129 + (11 - 129) * (t / 0.5))
                        else:
                            r = int(245 + (239 - 245) * ((t - 0.5) / 0.5))
                            g = int(158 + (68 - 158) * ((t - 0.5) / 0.5))
                            b = int(11 + (68 - 11) * ((t - 0.5) / 0.5))
                        return f"rgb({r},{g},{b})"

                    dd_rows = []
                    for i, (_, row) in enumerate(sector_df.iterrows()):
                        bg = "#0d1117" if i % 2 == 0 else "#111827"
                        cells = []
                        for col in _dd_avail:
                            val = row.get(col)
                            # Format
                            if val is None or (isinstance(val, float) and np.isnan(val)):
                                display = "—"
                                color = "#4b5563"
                            elif col == "Mã":
                                display = str(val)
                                color = "#60a5fa"
                            elif col in ("Giá 1T %","Giá 1M %","Giá 3M %"):
                                v = float(val)
                                display = f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
                                color = "#10b981" if v > 0 else ("#ef4444" if v < 0 else "#9ca3af")
                            elif col in ("Vốn hoá (tỷ)","Freefloat~30% (tỷ)","GTGD TB (tỷ)"):
                                display = f"{float(val):,.0f}"
                                color = "#e5e7eb"
                            elif col in ("Vol Avg 5","Vol Avg 10","Vol Avg 20"):
                                display = f"{float(val):,.1f}M"
                                color = "#e5e7eb"
                            elif col == "Vol 5/20 %":
                                v = float(val)
                                display = f"{v:.0f}%"
                                color = "#10b981" if v > 110 else ("#ef4444" if v < 90 else "#e5e7eb")
                            else:
                                display = f"{float(val):.1f}%"
                                color = "#e5e7eb"

                            # Render cell
                            if col == "Mã":
                                cells.append(f'<td style="{td_base}color:{color};font-weight:600">{display}</td>')
                            elif col in _amp_cols and val is not None and not (isinstance(val, float) and np.isnan(val)):
                                t = max(0, min(1, (float(val) - _dd_amp_min) / _dd_amp_rng))
                                bar_w = max(4, int(t * 100))
                                bar_c = _dd_amp_color(val)
                                cells.append(
                                    f'<td style="{td_base}padding:4px 6px;min-width:90px">'
                                    f'<div style="display:flex;align-items:center;gap:5px;justify-content:flex-end">'
                                    f'<span style="color:#9ca3af;font-size:11px">{display}</span>'
                                    f'<div style="width:60px;height:14px;background:#1a2234;border-radius:2px;overflow:hidden">'
                                    f'<div style="width:{bar_w}%;height:100%;background:{bar_c};border-radius:2px"></div>'
                                    f'</div></div></td>')
                            else:
                                cells.append(f'<td style="{td_base}color:{color};text-align:right">{display}</td>')

                        dd_rows.append(f'<tr style="background:{bg}">' + "".join(cells) + "</tr>")

                    dd_headers = "".join(f'<th style="{th_style}">{c}</th>' for c in _dd_avail)
                    dd_height = min(600, 52 + len(sector_df) * 36)
                    dd_html = f"""<div style="overflow-x:auto;border-radius:8px;border:1px solid #374151;background:#0d1117;max-height:{dd_height}px;overflow-y:auto">
<table style="width:100%;border-collapse:collapse">
<thead><tr>{dd_headers}</tr></thead>
<tbody>{"".join(dd_rows)}</tbody>
</table></div>"""
                    st.markdown(dd_html, unsafe_allow_html=True)

                    dd_csv = sector_df[_dd_avail].to_csv(index=False, encoding="utf-8-sig")
                    st.download_button(f"⬇️ Export {_selected_nganh}", data=dd_csv,
                                       file_name=f"sector_{_selected_nganh}_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                                       mime="text/csv", key="dd_export")
                else:
                    st.info(f"Không có dữ liệu ticker cho ngành {_selected_nganh}")

        # ── Nhận định thị trường ──────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 🧭 Nhận định tổng quan thị trường")

        def _build_commentary(breadth_data, mkt_data, idx_data):
            """Generate market commentary từ data có sẵn."""
            lines = []

            # 1. Đánh giá sức mạnh chung VNINDEX/VN30
            lines.append("**📊 Sức mạnh chung**")
            if idx_data is not None and not idx_data.empty:
                for idx_name in ["VNINDEX", "VN30"]:
                    chg_col = f"{idx_name}_chg"
                    if chg_col in idx_data.columns:
                        recent = idx_data[chg_col].dropna().head(5)
                        avg_chg = recent.mean()
                        up_days = (recent > 0).sum()
                        last_close = idx_data[idx_name].dropna().iloc[0] if idx_name in idx_data.columns else None
                        close_str = f" ({last_close:,.0f})" if last_close else ""
                        if avg_chg > 0.3:
                            trend = "tăng tích cực"
                            icon = "🟢"
                        elif avg_chg > 0:
                            trend = "đi ngang thiên tăng"
                            icon = "🟡"
                        elif avg_chg > -0.3:
                            trend = "đi ngang thiên giảm"
                            icon = "🟠"
                        else:
                            trend = "giảm rõ rệt"
                            icon = "🔴"
                        lines.append(f"- {icon} **{idx_name}**{close_str}: {trend} — 5 phiên gần nhất {up_days}/5 tăng, TB {avg_chg:+.2f}%/phiên")

            # 2. Breadth assessment
            if breadth_data:
                lines.append("")
                lines.append("**🌡️ Sức khỏe thị trường**")
                pct200 = breadth_data["above_ma200_pct"]
                ad = breadth_data["ad_ratio"]
                ov = breadth_data["rsi_oversold"]
                ob = breadth_data["rsi_overbought"]
                nnh = breadth_data["net_new_highs"]

                if pct200 > 50:
                    lines.append(f"- 🟢 {pct200:.0f}% mã trên MA200 — thị trường trong xu hướng tăng rộng")
                elif pct200 > 30:
                    lines.append(f"- 🟡 {pct200:.0f}% mã trên MA200 — thị trường phân hóa, chọn lọc")
                else:
                    lines.append(f"- 🔴 Chỉ {pct200:.0f}% mã trên MA200 — đa số cổ phiếu trong xu hướng giảm")

                if ad > 1.2:
                    lines.append(f"- A/D ratio {ad:.2f} — lực cầu chiếm ưu thế")
                elif ad < 0.8:
                    lines.append(f"- A/D ratio {ad:.2f} — lực bán áp đảo")

                if ov > 50:
                    lines.append(f"- ⚠️ {ov} mã RSI<30 — vùng quá bán rộng, cơ hội nếu có tín hiệu đảo chiều")
                if ob > 30:
                    lines.append(f"- ⚠️ {ob} mã RSI>70 — nhiều mã quá mua, cẩn trọng đuổi giá")

                if nnh > 10:
                    lines.append(f"- {nnh:+d} net new highs — thị trường tạo đỉnh mới tốt")
                elif nnh < -10:
                    lines.append(f"- {nnh:+d} net new highs — nhiều mã tạo đáy mới hơn đỉnh mới")

            # 3. Đánh giá ngành
            if mkt_data is not None and not mkt_data.empty:
                lines.append("")
                lines.append("**🏭 Nhóm ngành nổi bật**")

                # Ngành nên tập trung: Giá 1M > 0 AND Vol 5/20 > 100
                focus = mkt_data[
                    (mkt_data["Giá 1M %"].fillna(0) > 0) &
                    (mkt_data["Vol 5/20 %"].fillna(0) > 95)
                ].sort_values("Giá 1M %", ascending=False)

                if not focus.empty:
                    lines.append("- 🟢 **Nên tập trung:** " + ", ".join(
                        f'{r["Ngành"]} ({r["Giá 1M %"]:+.1f}%)'
                        for _, r in focus.head(5).iterrows()
                    ))
                else:
                    lines.append("- 🟡 Không có ngành nào vừa tăng giá 1M vừa có thanh khoản tốt")

                # Ngành nên tránh: Giá 1M < -3% OR (Giá 3M < -5% AND Vol giảm)
                avoid = mkt_data[
                    (mkt_data["Giá 1M %"].fillna(0) < -3) |
                    ((mkt_data["Giá 3M %"].fillna(0) < -5) & (mkt_data["Vol 5/20 %"].fillna(100) < 85))
                ].sort_values("Giá 1M %", ascending=True)

                if not avoid.empty:
                    lines.append("- 🔴 **Nên tránh:** " + ", ".join(
                        f'{r["Ngành"]} ({r["Giá 1M %"]:+.1f}%)'
                        for _, r in avoid.head(5).iterrows()
                    ))

                # 4. Top cổ phiếu trong ngành focus
                tick_data = st.session_state.get("_mkt_ticker_data")
                if tick_data is not None and not focus.empty:
                    lines.append("")
                    lines.append("**⭐ Cổ phiếu đáng chú ý trong ngành trọng tâm**")
                    for _, sector_row in focus.head(3).iterrows():
                        sector_name = sector_row["Ngành"]
                        tickers = tick_data[tick_data["Ngành"] == sector_name].copy()
                        if tickers.empty:
                            continue
                        # Chọn mã: Giá 1M > 0, Vol đủ lớn, sort theo Giá 1M
                        top = tickers[
                            (tickers["Giá 1M %"].fillna(0) > 0) &
                            (tickers["Vol Avg 20"].fillna(0) > 0.5)
                        ].sort_values("Giá 1M %", ascending=False).head(3)
                        if not top.empty:
                            picks = ", ".join(
                                f'**{r["Mã"]}** (1M:{r["Giá 1M %"]:+.1f}%, VH:{r["Vốn hoá (tỷ)"]:,.0f}tỷ)'
                                for _, r in top.iterrows()
                            )
                            lines.append(f"- {sector_name}: {picks}")

            return "\n".join(lines)

        commentary = _build_commentary(
            breadth if breadth else None,
            mkt_df,
            idx_df if not idx_df.empty else None
        )
        st.markdown(commentary)
        st.caption("⚠️ Nhận định tự động dựa trên dữ liệu kỹ thuật, không phải khuyến nghị đầu tư.")

        # ── Heatmap ngành (Treemap) ────────────────────────────────────────────
        tick_data = st.session_state.get("_mkt_ticker_data")
        if tick_data is not None and not tick_data.empty:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("#### 🗺️ Heatmap ngành — Vốn hoá & Biến động 1 tháng")
            try:
                import plotly.express as px

                tm_df = tick_data[["Mã","Ngành","Vốn hoá (tỷ)","Giá 1M %"]].copy()
                tm_df = tm_df[tm_df["Vốn hoá (tỷ)"].fillna(0) > 0].dropna(subset=["Giá 1M %"])
                tm_df = tm_df.nlargest(500, "Vốn hoá (tỷ)")

                if not tm_df.empty:
                    fig_tm = px.treemap(
                        tm_df, path=["Ngành", "Mã"],
                        values="Vốn hoá (tỷ)", color="Giá 1M %",
                        color_continuous_scale=["#ef4444","#1f2937","#10b981"],
                        color_continuous_midpoint=0,
                        range_color=[-15, 15],
                        hover_data={"Vốn hoá (tỷ)": ":,.0f", "Giá 1M %": ":+.1f"},
                    )
                    fig_tm.update_layout(
                        height=600,
                        paper_bgcolor="#0a0e1a",
                        font=dict(color="#e5e7eb", size=11),
                        margin=dict(l=5, r=5, t=30, b=5),
                        coloraxis_colorbar=dict(
                            title="1M %", ticksuffix="%",
                            bgcolor="#111827", bordercolor="#1f2937",
                        ),
                    )
                    fig_tm.update_traces(
                        textinfo="label+value",
                        textfont=dict(size=10),
                        hovertemplate="<b>%{label}</b><br>Vốn hoá: %{value:,.0f} tỷ<br>1M: %{color:+.1f}%<extra></extra>",
                    )
                    st.plotly_chart(fig_tm, use_container_width=True)
            except ImportError:
                st.info("Cài plotly để xem heatmap: `pip install plotly`")

        # ── Chart xu hướng ────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 📈 Biến động giá theo ngành (1 tháng vs 3 tháng)")
        try:
            import plotly.graph_objects as go
            chart_df = mkt_df[mkt_df["Giá 1M %"].notna()].copy()
            chart_df = chart_df.sort_values("Giá 1M %", ascending=True)
            colors1m = ["#10b981" if v > 0 else "#ef4444" for v in chart_df["Giá 1M %"]]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=chart_df["Ngành"], x=chart_df["Giá 1M %"],
                name="1 Tháng", orientation="h",
                marker_color=colors1m, opacity=0.85,
            ))
            if "Giá 3M %" in chart_df.columns and chart_df["Giá 3M %"].notna().any():
                fig.add_trace(go.Scatter(
                    y=chart_df["Ngành"], x=chart_df["Giá 3M %"],
                    name="3 Tháng", mode="markers",
                    marker=dict(color="#fbbf24", size=8, symbol="diamond"),
                ))
            fig.update_layout(
                height=max(350, len(chart_df)*22),
                paper_bgcolor="#0a0e1a", plot_bgcolor="#0d1117",
                font=dict(color="#9ca3af", size=11),
                xaxis=dict(gridcolor="#1f2937", zeroline=True,
                           zerolinecolor="#374151", zerolinewidth=2,
                           ticksuffix="%"),
                yaxis=dict(gridcolor="#1f2937"),
                margin=dict(l=0, r=80, t=20, b=20),
                legend=dict(bgcolor="#111827", bordercolor="#1f2937", borderwidth=1),
            )
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.info("Cài plotly để xem chart: `pip install plotly`")

