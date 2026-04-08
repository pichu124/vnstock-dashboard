"""
vnstock_analysis.py — Dashboard Phân Tích Cổ Phiếu
====================================================
Technical + Fundamental analysis trên cùng 1 trang.
Chọn mã bằng ô tìm kiếm hoặc từ danh sách screener.

Run:
  streamlit run vnstock_analysis.py
"""

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import streamlit as st
import streamlit.components.v1 as components

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="VnStock Analysis",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Paths ─────────────────────────────────────────────────────────────────────
WAREHOUSE   = Path("data_warehouse")
PRICES_DIR  = WAREHOUSE / "prices"
RESULTS_PATH = WAREHOUSE / "_meta" / "screener_results.json"
INDUSTRY_PATH = WAREHOUSE / "_meta" / "industry_classification.parquet"

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.stApp { background: #0a0e1a; }
.card {
    background: #111827; border: 1px solid #1f2937;
    border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
}
.card-title {
    font-size: 11px; color: #6b7280; text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 8px;
}
.signal-buy  { color: #10b981; font-weight: 600; }
.signal-sell { color: #ef4444; font-weight: 600; }
.signal-neutral { color: #9ca3af; }
.big-num {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 28px; font-weight: 500; color: #f9fafb;
}
.section-title {
    font-size: 13px; font-weight: 500; color: #6b7280;
    text-transform: uppercase; letter-spacing: 0.06em;
    margin: 20px 0 10px;
}
.fscore-bar {
    height: 8px; border-radius: 4px; background: #1f2937; margin: 6px 0;
}
.fscore-fill {
    height: 8px; border-radius: 4px;
    transition: width 0.5s ease;
}
.tag {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 500; margin: 2px;
}
</style>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
# Data loaders
# ═════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_price_history(ticker: str, days: int = 365) -> pd.DataFrame:
    ticker_dir = PRICES_DIR / f"ticker={ticker.upper()}"
    if not ticker_dir.exists():
        return pd.DataFrame()
    cutoff_year = datetime.now().year - (days // 365 + 1)
    frames = []
    for yd in sorted(ticker_dir.glob("year=*")):
        try:
            yr = int(yd.name.replace("year=", ""))
            if yr < cutoff_year:
                continue
            for pf in yd.glob("*.parquet"):
                frames.append(pq.read_table(str(pf),
                    columns=["time","open","high","low","close","volume"]).to_pandas())
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    cutoff = datetime.now() - timedelta(days=days)
    df = df[df["time"] >= cutoff].sort_values("time").reset_index(drop=True)
    return df


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

def render_chart(df: pd.DataFrame, ticker: str):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        st.info("Cài plotly để xem chart: `pip install plotly`")
        return

    ind = compute_indicators(df)
    if ind.empty:
        return

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.03,
    )

    # ── Candlestick ────────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=ind["time"], open=ind["open"], high=ind["high"],
        low=ind["low"], close=ind["close"],
        name="Price",
        increasing_line_color="#10b981",
        decreasing_line_color="#ef4444",
        increasing_fillcolor="#10b981",
        decreasing_fillcolor="#ef4444",
    ), row=1, col=1)

    # EMAs
    for span, color, width in [(9,"#60a5fa",1), (21,"#a78bfa",1), (50,"#fbbf24",1.5), (200,"#f97316",2)]:
        col_name = f"ema{span}"
        if col_name in ind.columns:
            fig.add_trace(go.Scatter(
                x=ind["time"], y=ind[col_name],
                name=f"EMA{span}", line=dict(color=color, width=width),
                opacity=0.8,
            ), row=1, col=1)

    # BB
    if "bb_up" in ind.columns:
        fig.add_trace(go.Scatter(
            x=ind["time"], y=ind["bb_up"], name="BB Upper",
            line=dict(color="#374151", width=1, dash="dash"), showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=ind["time"], y=ind["bb_lo"], name="BB Lower",
            line=dict(color="#374151", width=1, dash="dash"),
            fill="tonexty", fillcolor="rgba(55,65,81,0.15)", showlegend=False,
        ), row=1, col=1)

    # ── Volume ─────────────────────────────────────────────────────────────────
    colors = ["#10b981" if c >= o else "#ef4444"
              for c, o in zip(ind["close"], ind["open"])]
    fig.add_trace(go.Bar(
        x=ind["time"], y=ind["volume"], name="Volume",
        marker_color=colors, opacity=0.7,
    ), row=2, col=1)
    if "vol_ma20" in ind.columns:
        fig.add_trace(go.Scatter(
            x=ind["time"], y=ind["vol_ma20"], name="Vol MA20",
            line=dict(color="#fbbf24", width=1), showlegend=False,
        ), row=2, col=1)

    # ── MACD ───────────────────────────────────────────────────────────────────
    if "macd" in ind.columns:
        macd_colors = ["#10b981" if v >= 0 else "#ef4444" for v in ind["macd_hist"].fillna(0)]
        fig.add_trace(go.Bar(
            x=ind["time"], y=ind["macd_hist"], name="MACD Hist",
            marker_color=macd_colors, opacity=0.8,
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=ind["time"], y=ind["macd"], name="MACD",
            line=dict(color="#60a5fa", width=1.5),
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=ind["time"], y=ind["macd_signal"], name="Signal",
            line=dict(color="#f97316", width=1.5),
        ), row=3, col=1)

    fig.update_layout(
        height=600,
        paper_bgcolor="#0a0e1a",
        plot_bgcolor="#0d1117",
        font=dict(family="IBM Plex Sans", color="#9ca3af", size=11),
        legend=dict(
            bgcolor="#111827", bordercolor="#1f2937", borderwidth=1,
            font=dict(size=10), orientation="h", y=1.02,
        ),
        xaxis_rangeslider_visible=False,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    for i in range(1, 4):
        fig.update_xaxes(gridcolor="#1f2937", row=i, col=1)
        fig.update_yaxes(gridcolor="#1f2937", row=i, col=1)

    st.plotly_chart(fig, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# Fundamental data loader (từ vnstock API)
# ═════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def load_fundamental(ticker: str) -> dict:
    """Load ratios, P/E, ROE, EPS từ vnstock. Cache 1 giờ."""
    result = {}
    try:
        try:
            from vnstock_data import Fundamental
            fund = Fundamental().equity(ticker)
            ratios = fund.ratio(period="Y")
        except ImportError:
            from vnstock import Vnstock
            stock  = Vnstock().stock(symbol=ticker, source="VCI")
            ratios = stock.finance.ratio(period="year", lang="vi")

        if ratios is not None and not ratios.empty:
            # Flatten MultiIndex
            if isinstance(ratios.columns, pd.MultiIndex):
                ratios.columns = [
                    "_".join(str(c) for c in col if str(c) not in ("","nan")).strip("_")
                    for col in ratios.columns
                ]

            def find(df, *keys):
                lc = {c.lower(): c for c in df.columns}
                for k in keys:
                    if k.lower() in lc:
                        return lc[k.lower()]
                return None

            def get(col):
                if col is None: return None
                try:
                    v = ratios[col].iloc[0]
                    return float(v) if not pd.isna(v) else None
                except Exception:
                    return None

            result["pe"]  = get(find(ratios, "p/e", "định giá_p/e", "pricetoearning"))
            result["pb"]  = get(find(ratios, "p/b", "định giá_p/b", "pricetobook"))
            result["roe"] = get(find(ratios, "roe", "sinh lợi_roe", "return_on_equity"))
            result["roa"] = get(find(ratios, "roa", "sinh lợi_roa", "return_on_assets"))
            result["eps"] = get(find(ratios, "eps", "định giá_eps", "earning_per_share"))
            result["gross_margin"] = get(find(ratios, "gross_margin", "biên lợi nhuận gộp"))
            result["net_margin"]   = get(find(ratios, "net_margin", "biên lợi nhuận ròng", "net_profit_margin"))
            result["debt_ratio"]   = get(find(ratios, "debt_ratio", "debt_to_equity", "tỷ lệ nợ"))

            # Revenue trend (2 năm gần nhất)
            rev_col = find(ratios, "revenue", "doanh thu", "net_revenue")
            if rev_col and len(ratios) >= 2:
                r0 = float(ratios[rev_col].iloc[0]) if not pd.isna(ratios[rev_col].iloc[0]) else None
                r1 = float(ratios[rev_col].iloc[1]) if not pd.isna(ratios[rev_col].iloc[1]) else None
                if r0 and r1 and r1 != 0:
                    result["revenue_growth"] = round((r0 - r1) / abs(r1) * 100, 1)
    except Exception as e:
        result["error"] = str(e)[:100]
    return result


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

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔬 Phân Tích Cổ Phiếu")

    # Ô tìm kiếm trực tiếp
    ticker_input = st.text_input(
        "Nhập mã cổ phiếu", value="", placeholder="VD: VCB, FPT, HPG...",
        key="ticker_input"
    ).upper().strip()

    st.divider()

    # Chọn từ screener
    st.markdown("**Hoặc chọn từ Screener**")
    screener_data = load_screener_results()
    if screener_data and screener_data.get("presets"):
        preset_names = list(screener_data["presets"].keys())
        selected_preset = st.selectbox(
            "Preset", ["—"] + preset_names,
            format_func=lambda p: p if p=="—" else f"{p} ({screener_data['presets'][p].get('count',0)})"
        )
        if selected_preset != "—":
            results = screener_data["presets"][selected_preset].get("results", [])
            tickers_in_preset = [r["ticker"] for r in results if r.get("ticker")]
            if tickers_in_preset:
                selected_from_screener = st.selectbox(
                    "Chọn mã", tickers_in_preset,
                    format_func=lambda t: f"{t} — {next((r.get('industry','') for r in results if r['ticker']==t), '')}"
                )
                if st.button("📊 Phân tích mã này", use_container_width=True):
                    st.session_state["analyze_ticker"] = selected_from_screener
    else:
        st.caption("Chưa có dữ liệu screener. Chạy `python vnstock_runner.py` trước.")

    st.divider()

    # Lookback period
    lookback = st.select_slider(
        "Khoảng thời gian",
        options=[90, 180, 365, 730],
        value=365,
        format_func=lambda v: {90:"3 tháng",180:"6 tháng",365:"1 năm",730:"2 năm"}[v]
    )

    # Load fundamental toggle
    load_fund = st.toggle("Tải dữ liệu cơ bản (API)", value=False,
                          help="Gọi vnstock API để lấy P/E, ROE, EPS...")


# ── Xác định ticker cần phân tích ─────────────────────────────────────────────
ticker = ticker_input or st.session_state.get("analyze_ticker", "")

if not ticker:
    # Landing page
    st.markdown("## 🔬 VnStock Analysis Dashboard")
    st.markdown('<p style="color:#6b7280">Nhập mã cổ phiếu ở sidebar hoặc chọn từ danh sách Screener để bắt đầu phân tích.</p>', unsafe_allow_html=True)

    # Hiện top movers nếu có screener data
    if screener_data and screener_data.get("presets"):
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**⚡ Momentum mạnh nhất**")
            mom = screener_data["presets"].get("momentum", {}).get("results", [])[:5]
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
            ov = screener_data["presets"].get("oversold", {}).get("results", [])[:5]
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
render_chart(df, ticker)

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

        if fund.get("error"):
            st.warning(f"Lỗi tải dữ liệu cơ bản: {fund['error']}")
        else:
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
