"""
vnstock_platform_v2.py — Vietnam Stock Analysis Platform
=========================================================
Merged best of v1 (battle-tested column mapping, TA, Piotroski) with v2
(vnstock_data Unified UI, vnstock_chart CandleChart, CLI).

Auto-detects environment:
  - vnstock_data (Unified UI v3+)  → preferred
  - vnstock (free, v3.4+)          → fallback

Stack:
  rich          — terminal output
  vnstock_chart — CandleChart HTML (optional)
  vnstock_ta    — Indicator/Plotter (optional, falls back to pure-pandas)

Run:
  python vnstock_platform_v2.py
  python vnstock_platform_v2.py --symbol FPT --open-chart
  python vnstock_platform_v2.py --symbols VCB FPT HPG --export-csv
"""

import argparse
import os
import re as _re
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Rich ──────────────────────────────────────────────────────────────────────
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

# ── Local warehouse (ưu tiên dùng trước API) ─────────────────────────────────
_WAREHOUSE_ROOT = Path(os.getenv("WAREHOUSE_ROOT", "data_warehouse"))
_PRICES_DIR     = _WAREHOUSE_ROOT / "prices"
HAS_WAREHOUSE   = _PRICES_DIR.exists()
if HAS_WAREHOUSE:
    console.log(f"[green]📦 Local warehouse detected:[/green] {_WAREHOUSE_ROOT.resolve()}")
else:
    console.log("[dim]ℹ No local warehouse — using API only[/dim]")


def _load_from_warehouse(ticker: str, start: str, end: str) -> pd.DataFrame:
    """
    Đọc OHLCV từ local Parquet warehouse — nhanh hơn API ~100x.
    Trả về DataFrame rỗng nếu không tìm thấy.
    """
    if not HAS_WAREHOUSE:
        return pd.DataFrame()

    ticker_dir = _PRICES_DIR / f"ticker={ticker.upper()}"
    if not ticker_dir.exists():
        return pd.DataFrame()

    try:
        import pyarrow.parquet as _pq

        start_year = int(start[:4]) if start else 2000
        end_year   = int(end[:4])   if end   else datetime.now().year

        frames = []
        for year in range(start_year, end_year + 1):
            year_dir = ticker_dir / f"year={year}"
            if not year_dir.exists():
                continue
            for pf in year_dir.glob("*.parquet"):
                tbl = _pq.read_table(str(pf),
                      columns=["time","open","high","low","close","volume"])
                frames.append(tbl.to_pandas())
                del tbl

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time")

        # Lọc theo ngày
        if start:
            df = df[df["time"] >= pd.Timestamp(start)]
        if end:
            df = df[df["time"] <= pd.Timestamp(end)]

        df = df.reset_index(drop=True)
        console.log(
            f"  [green]📦 Local[/green] {ticker}: "
            f"{len(df)} rows ({start} → {end})"
        )
        return df

    except Exception as e:
        console.log(f"  [dim]⚠ Warehouse read error [{ticker}]: {e}[/dim]")
        return pd.DataFrame()
try:
    from vnstock_data import Fundamental, Market, Reference
    USE_UNIFIED = True
    console.log("[green]✅ Using vnstock_data (Unified UI)[/green]")
except ImportError:
    USE_UNIFIED = False
    console.log("[yellow]⚠ vnstock_data not found — using vnstock (free)[/yellow]")
    try:
        from vnstock import Vnstock
    except ImportError:
        console.print("[red]❌ Neither vnstock_data nor vnstock is installed.[/red]")
        console.print("Run: pip install vnstock")
        sys.exit(1)

# ── vnstock_chart (optional) ──────────────────────────────────────────────────
try:
    from vnstock_chart import CandleChart
    HAS_CHART = True
except ImportError:
    HAS_CHART = False

# ── vnstock_ta (optional — falls back to pure-pandas TA) ─────────────────────
try:
    from vnstock_ta import Indicator as TAIndicator
    HAS_TA_LIB = True
except ImportError:
    HAS_TA_LIB = False


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")

def _strip_html(text: str) -> str:
    return _re.sub(r"<[^>]+>", "", str(text)).strip()

def _fmt_large(v) -> str:
    try:
        n = float(v)
        if n >= 1e12: return f"{n/1e12:.2f} nghìn tỷ VND"
        if n >= 1e9:  return f"{n/1e9:.2f} tỷ VND"
        if n >= 1e6:  return f"{n/1e6:.2f} triệu VND"
        return f"{n:,.0f}"
    except Exception:
        return str(v)

def _flatten_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex or tuple columns to plain strings (from v1)."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join(str(c) for c in col if str(c) not in ("", "nan")).strip("_")
            for col in df.columns
        ]
    else:
        df.columns = [
            "_".join(str(c) for c in col).strip("_") if isinstance(col, tuple) else str(col)
            for col in df.columns
        ]
    return df


# ═════════════════════════════════════════════════════════════════════════════
# DataClient — wraps both vnstock_data and vnstock APIs
# ═════════════════════════════════════════════════════════════════════════════

class DataClient:
    """Unified data access: vnstock_data Unified UI or vnstock free."""

    def __init__(self, symbol: str, source: str = "VCI"):
        self.symbol = symbol.upper()
        self.source = source
        if not USE_UNIFIED:
            self._stock = Vnstock().stock(symbol=self.symbol, source=self.source)

    # ── Price ─────────────────────────────────────────────────────────────────

    def get_price_history(self, start: str, end: str, interval: str = "1D") -> pd.DataFrame:
        console.log(f"  📊 Fetching price history [{self.symbol}] {start} → {end} ({interval})")

        # ✅ Thử local warehouse trước
        df = _load_from_warehouse(self.symbol, start, end)
        if not df.empty:
            return df

        # Fallback: gọi API
        console.log(f"  [dim]→ Falling back to API[/dim]")
        try:
            if USE_UNIFIED:
                df = Market().equity(self.symbol).ohlcv(start=start, end=end)
            else:
                df = self._stock.quote.history(start=start, end=end, interval=interval)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.copy()
            df.columns = [c.lower() for c in df.columns]
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"])
                df = df.sort_values("time").reset_index(drop=True)
            return df
        except Exception as e:
            console.log(f"  [yellow]⚠ Price error: {e}[/yellow]")
            return pd.DataFrame()

    # ── Overview ──────────────────────────────────────────────────────────────

    def get_overview(self) -> pd.DataFrame:
        console.log(f"  🏢 Fetching company overview [{self.symbol}]")
        try:
            if USE_UNIFIED:
                return Reference().company(self.symbol).info()
            else:
                return self._stock.company.overview()
        except Exception as e:
            console.log(f"  [yellow]⚠ Overview error: {e}[/yellow]")
            return pd.DataFrame()

    # ── Ratios ────────────────────────────────────────────────────────────────

    def get_ratios(self, period: str = "year") -> pd.DataFrame:
        console.log(f"  📐 Fetching financial ratios [{self.symbol}]")
        try:
            if USE_UNIFIED:
                df = Fundamental().equity(self.symbol).ratio()
            else:
                df = self._stock.finance.ratio(period=period, lang="en")
            if df is None or df.empty:
                return pd.DataFrame()
            return _flatten_cols(df)
        except Exception as e:
            console.log(f"  [yellow]⚠ Ratios error: {e}[/yellow]")
            return pd.DataFrame()

    # ── Balance Sheet & Income ────────────────────────────────────────────────

    def get_balance_sheet(self, period: str = "year") -> pd.DataFrame:
        console.log(f"  📋 Fetching balance sheet [{self.symbol}]")
        try:
            if USE_UNIFIED:
                df = Fundamental().equity(self.symbol).balance_sheet(period=period)
            else:
                df = self._stock.finance.balance_sheet(period=period, lang="en")
            return _flatten_cols(df) if df is not None else pd.DataFrame()
        except Exception as e:
            console.log(f"  [yellow]⚠ Balance sheet error: {e}[/yellow]")
            return pd.DataFrame()

    def get_income_statement(self, period: str = "year") -> pd.DataFrame:
        console.log(f"  📋 Fetching income statement [{self.symbol}]")
        try:
            if USE_UNIFIED:
                df = Fundamental().equity(self.symbol).income_statement(period=period)
            else:
                df = self._stock.finance.income_statement(period=period, lang="en")
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            console.log(f"  [yellow]⚠ Income statement error: {e}[/yellow]")
            return pd.DataFrame()

    # ── News ──────────────────────────────────────────────────────────────────

    def get_news(self, limit: int = 5) -> pd.DataFrame:
        console.log(f"  📰 Fetching news [{self.symbol}]")
        try:
            if USE_UNIFIED:
                df = Reference().company(self.symbol).news()
            else:
                # vnstock Company.news() không nhận tham số limit
                df = self._stock.company.news()
            return df.head(limit) if df is not None else pd.DataFrame()
        except Exception as e:
            console.log(f"  [yellow]⚠ News error: {e}[/yellow]")
            return pd.DataFrame()


# ═════════════════════════════════════════════════════════════════════════════
# TechnicalAnalyzer — pure-pandas RSI/MACD/EMA/BB (from v1, battle-tested)
# ═════════════════════════════════════════════════════════════════════════════

class TechnicalAnalyzer:
    """RSI, MACD, EMA, Bollinger Bands — pure pandas, no extra deps."""

    def __init__(self, price_df: pd.DataFrame):
        if price_df is None or price_df.empty:
            raise ValueError("price_df is empty.")
        self.df = price_df.copy().sort_values("time").reset_index(drop=True)
        self.df["close"] = pd.to_numeric(self.df["close"], errors="coerce")
        self.df.dropna(subset=["close"], inplace=True)
        self._ind: Optional[pd.DataFrame] = None

    def _compute(self) -> pd.DataFrame:
        if self._ind is not None:
            return self._ind
        df = self.df.copy()
        c  = df["close"]

        # RSI 14
        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        df["rsi_14"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

        # EMAs
        for span in (9, 21, 50, 200):
            df[f"ema_{span}"] = c.ewm(span=span, adjust=False).mean()

        # MACD 12-26-9
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        df["macd_line"]   = ema12 - ema26
        df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
        df["macd_hist"]   = df["macd_line"] - df["macd_signal"]

        # Bollinger 20, 2σ
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        df["bb_upper"] = sma20 + 2 * std20
        df["bb_lower"] = sma20 - 2 * std20
        df["bb_mid"]   = sma20

        self._ind = df
        return df

    def get_signals(self) -> dict:
        df  = self._compute()
        lat = df.iloc[-1]
        prv = df.iloc[-2] if len(df) > 1 else lat

        sig = {
            "current_price":   round(float(lat["close"]), 2),
            "rsi_14":          round(float(lat.get("rsi_14",  np.nan)), 2),
            "macd_histogram":  round(float(lat.get("macd_hist", np.nan)), 4),
            "ema_9":           round(float(lat.get("ema_9",   np.nan)), 2),
            "ema_21":          round(float(lat.get("ema_21",  np.nan)), 2),
        }

        # RSI signal
        r = sig["rsi_14"]
        sig["rsi_signal"] = "BUY" if r < 30 else ("SELL" if r > 70 else "NEUTRAL")

        # MACD signal
        h, ph = sig["macd_histogram"], float(prv.get("macd_hist", np.nan))
        if np.isnan(h) or np.isnan(ph):
            sig["macd_signal"] = "NEUTRAL"
        elif h > 0 and ph <= 0:
            sig["macd_signal"] = "BUY"
        elif h < 0 and ph >= 0:
            sig["macd_signal"] = "SELL"
        else:
            sig["macd_signal"] = "BUY" if h > 0 else "SELL"

        # EMA trend
        e9, e21 = sig["ema_9"], sig["ema_21"]
        sig["ema_trend"] = "NEUTRAL" if np.isnan(e9) or np.isnan(e21) else (
            "BUY" if e9 > e21 else "SELL"
        )

        # BB signal
        p, bu, bl = sig["current_price"], float(lat.get("bb_upper", np.nan)), float(lat.get("bb_lower", np.nan))
        if np.isnan(bu) or np.isnan(bl):
            sig["bb_signal"] = "NEUTRAL"
        elif p >= bu:
            sig["bb_signal"] = "SELL"
        elif p <= bl:
            sig["bb_signal"] = "BUY"
        else:
            sig["bb_signal"] = "NEUTRAL"

        return sig

    def score(self) -> float:
        s = self.get_signals()
        m = {"BUY": 1, "NEUTRAL": 0, "SELL": -1}
        raw = [
            m.get(s["rsi_signal"],  0) * 1.5,
            m.get(s["macd_signal"], 0) * 1.5,
            m.get(s["ema_trend"],   0) * 1.0,
            m.get(s["bb_signal"],   0) * 0.5,
        ]
        return round(sum(raw) / 4.5, 4)

    def get_dataframe(self) -> pd.DataFrame:
        return self._compute()


# ═════════════════════════════════════════════════════════════════════════════
# FundamentalAnalyzer — Piotroski F-Score (from v1, unchanged)
# ═════════════════════════════════════════════════════════════════════════════

class FundamentalAnalyzer:
    """Piotroski F-Score (0-9) adapted for Vietnamese equities."""

    def __init__(self, ratios_df, balance_df, income_df):
        self.ratios  = ratios_df  if ratios_df  is not None else pd.DataFrame()
        self.balance = balance_df if balance_df is not None else pd.DataFrame()
        self.income  = income_df  if income_df  is not None else pd.DataFrame()
        self._details: Optional[dict] = None

    def _get(self, df, col, row=0):
        try:
            v = df[col].iloc[row]
            return float(v) if not pd.isna(v) else np.nan
        except Exception:
            return np.nan

    def _find(self, df, *keys):
        lc = {c.lower(): c for c in df.columns}
        for k in keys:
            if k.lower() in lc:
                return lc[k.lower()]
        return None

    def get_details(self) -> dict:
        if self._details:
            return self._details
        r = {}

        roa_c  = self._find(self.ratios,  "roa", "return_on_assets")
        ocf_c  = self._find(self.income,  "operating_cash_flow", "cfo")
        ni_c   = self._find(self.income,  "net_income", "net_profit", "profit_after_tax")
        der_c  = self._find(self.ratios,  "debt_ratio", "debt_to_equity")
        cr_c   = self._find(self.ratios,  "current_ratio")
        sh_c   = self._find(self.balance, "shares_outstanding", "outstanding_shares")
        gm_c   = self._find(self.ratios,  "gross_margin", "gross_profit_margin")
        at_c   = self._find(self.ratios,  "asset_turnover")

        def sg(col, df, row=0): return self._get(df, col, row) if col else np.nan

        roa0, roa1 = sg(roa_c, self.ratios, 0), sg(roa_c, self.ratios, 1)
        ocf        = sg(ocf_c, self.income)
        ni         = sg(ni_c,  self.income)
        dr0, dr1   = sg(der_c, self.ratios, 0), sg(der_c, self.ratios, 1)
        cr0, cr1   = sg(cr_c,  self.ratios, 0), sg(cr_c,  self.ratios, 1)
        sh0, sh1   = sg(sh_c,  self.balance, 0), sg(sh_c,  self.balance, 1)
        gm0, gm1   = sg(gm_c,  self.ratios, 0), sg(gm_c,  self.ratios, 1)
        at0, at1   = sg(at_c,  self.ratios, 0), sg(at_c,  self.ratios, 1)

        def ok(*args): return not any(np.isnan(a) for a in args)

        r["F1"] = {"score": int(ok(roa0) and roa0>0),          "note": "Positive ROA"}
        r["F2"] = {"score": int(ok(ocf) and ocf>0),            "note": "Positive OCF"}
        r["F3"] = {"score": int(ok(roa0,roa1) and roa0>roa1),  "note": "ROA improving YoY"}
        r["F4"] = {"score": int(ok(ocf,ni) and ocf>ni),        "note": "OCF > Net Income"}
        r["F5"] = {"score": int(ok(dr0,dr1) and dr0<dr1),      "note": "Debt ratio decreasing"}
        r["F6"] = {"score": int(ok(cr0,cr1) and cr0>cr1),      "note": "Current ratio improving"}
        r["F7"] = {"score": int(not ok(sh0,sh1) or sh0<=sh1),  "note": "No share dilution"}
        r["F8"] = {"score": int(ok(gm0,gm1) and gm0>gm1),      "note": "Gross margin improving"}
        r["F9"] = {"score": int(ok(at0,at1) and at0>at1),       "note": "Asset turnover improving"}

        self._details = r
        return r

    def score(self) -> int:
        return sum(v["score"] for v in self.get_details().values())

    def score_normalized(self) -> float:
        return round((self.score() / 9) * 2 - 1, 4)

    def grade(self) -> str:
        s = self.score()
        if s >= 8: return "STRONG BUY  (F≥8)"
        if s >= 6: return "BUY         (F≥6)"
        if s >= 4: return "HOLD        (F≥4)"
        if s >= 2: return "SELL        (F≥2)"
        return           "STRONG SELL (F<2)"


# ═════════════════════════════════════════════════════════════════════════════
# ConsensusEngine — 40% tech + 60% fundamental (from v1)
# ═════════════════════════════════════════════════════════════════════════════

class ConsensusEngine:
    """Aggregates technical and fundamental scores."""
    TW, FW = 0.40, 0.60

    def __init__(self, tech: float, fund: float, symbol: str):
        self.tech  = tech
        self.fund  = fund
        self.symbol = symbol
        self.composite = round(tech * self.TW + fund * self.FW, 4)

    def recommendation(self) -> str:
        c = self.composite
        if c >  0.60: return "STRONG BUY 🟢🟢"
        if c >  0.20: return "BUY 🟢"
        if c >= -0.20: return "HOLD 🟡"
        if c >= -0.60: return "SELL 🔴"
        return               "STRONG SELL 🔴🔴"

    def summary(self) -> dict:
        return {
            "symbol": self.symbol,
            "tech_score": self.tech,
            "fund_score": self.fund,
            "composite": self.composite,
            "recommendation": self.recommendation(),
        }


# ═════════════════════════════════════════════════════════════════════════════
# Ratio extraction — battle-tested column substrings from v1
# ═════════════════════════════════════════════════════════════════════════════

_RATIO_TARGETS = {
    "pe":            ["định giá_p/e",  "p/e",  "pricetoearning",  "price_to_earning",  "ratio_pe"],
    "pb":            ["định giá_p/b",  "p/b",  "pricetobook",     "price_to_book",     "ratio_pb"],
    "roe":           ["sinh lợi_roe",  "roe",  "return_on_equity"],
    "roa":           ["sinh lợi_roa",  "roa",  "return_on_assets"],
    "eps":           ["định giá_eps",  "eps",  "earning_per_share"],
    "net_margin":    ["net profit margin", "net_profit_margin", "profit_margin"],
    "dividend_yield":["dividend yield", "dividend_yield"],
}

def _extract_ratios(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    col_lower = {c.lower(): c for c in df.columns}
    ratios = {}
    for label, subs in _RATIO_TARGETS.items():
        for sub in subs:
            for cl, corig in col_lower.items():
                if sub in cl:
                    try:
                        v = df[corig].iloc[0]
                        if not pd.isna(v):
                            ratios[label] = round(float(v), 4)
                    except Exception:
                        pass
                    break
            if label in ratios:
                break
    return ratios


# ═════════════════════════════════════════════════════════════════════════════
# News cleaning — exact + fuzzy mapping + Unix ms timestamp (from v1)
# ═════════════════════════════════════════════════════════════════════════════

def _clean_news(df: pd.DataFrame, limit: int = 5) -> list[dict]:
    if df is None or df.empty:
        return []

    EXACT = {
        "public_date":      "published_date",
        "news_title":       "title",
        "news_source_link": "source",
    }
    DATE_K   = ["publish_date","publishdate","public_date","date","ngay","created","updated"]
    TITLE_K  = ["news_title","title","tieu","headline"]
    SOURCE_K = ["news_source_link","source_link","source","nguon"]

    remap = {c: EXACT[c] for c in df.columns if c in EXACT}
    mapped = set(remap.values())
    for c in df.columns:
        if c in remap: continue
        cl = c.lower()
        if "published_date" not in mapped and any(k in cl for k in DATE_K):
            remap[c] = "published_date"; mapped.add("published_date")
        elif "title" not in mapped and any(k in cl for k in TITLE_K):
            remap[c] = "title"; mapped.add("title")
        elif "source" not in mapped and any(k in cl for k in SOURCE_K):
            remap[c] = "source"; mapped.add("source")

    df = df.rename(columns=remap)

    # Fix duplicate columns (title mapped twice)
    df = df.loc[:, ~df.columns.duplicated()]

    # Strip HTML from title
    if "title" in df.columns:
        df["title"] = df["title"].astype(str).apply(
            lambda x: _re.sub(r"<[^>]+>", "", x).strip()
        )

    # Parse date — handles Unix ms or ISO string
    if "published_date" in df.columns:
        def _parse(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return ""
            try:
                f = float(v)
                if f > 1e10: f = f / 1000  # Unix ms → seconds
                return datetime.fromtimestamp(f).strftime("%Y-%m-%d")
            except Exception:
                s = str(v).strip()
                return s[:10] if s not in ("nan", "None", "NaT") else ""
        df["published_date"] = df["published_date"].apply(_parse)

    # Shorten source URL to domain
    if "source" in df.columns:
        df["source"] = df["source"].astype(str).apply(
            lambda x: x.replace("https://","").replace("http://","").split("/")[0]
            if str(x).startswith("http") else x
        )

    for col in ["published_date", "title", "source"]:
        if col not in df.columns:
            df[col] = ""

    return df.head(limit).to_dict("records")


# ═════════════════════════════════════════════════════════════════════════════
# CandleChart export
# ═════════════════════════════════════════════════════════════════════════════

def _export_chart(price_df: pd.DataFrame, symbol: str, output_dir: str = ".") -> str | None:
    if not HAS_CHART or price_df.empty:
        return None
    console.log(f"  🖼  Rendering CandleChart [{symbol}]")
    try:
        df = price_df.copy()
        if "time" not in df.columns and isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
        df["time"] = pd.to_datetime(df["time"])

        indicators = []
        if len(df) >= 20:
            df["sma20"] = df["close"].rolling(20).mean()
            indicators.append({"name": "SMA 20", "data": df["sma20"].tolist(), "color": "#f1c40f"})

        chart = CandleChart(
            df=df,
            mode="overlay" if indicators else "candle",
            indicators=indicators if indicators else None,
            title=f"{symbol} — Price Chart",
            theme="dark",
            width=1100, height=560,
        )
        path = Path(output_dir) / f"{symbol}_chart.html"
        chart.to_html(str(path))
        console.log(f"  ✅ Chart saved → {path}")
        return str(path)
    except Exception as e:
        console.log(f"  [yellow]⚠ Chart error: {e}[/yellow]")
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Terminal rendering (adapted from v1 _print_snapshot)
# ═════════════════════════════════════════════════════════════════════════════

def _print_snapshot(symbol, overview_df, price_df, ratios, news_list, tech_signals=None, days=30):
    console.rule(f"[bold cyan]📸 Company Snapshot: {symbol}[/bold cyan]", style="cyan")

    # ── Overview ──────────────────────────────────────────────────────────
    ov_lines = []
    if overview_df is not None and not overview_df.empty:
        ov = overview_df.iloc[0]
        def _ov(label, *keys):
            for k in keys:
                v = ov.get(k)
                if v is not None and str(v).strip() not in ("", "nan", "NaN"):
                    ov_lines.append(f"  [bold]{label}:[/bold] {v}")
                    return
        _ov("Ticker",   "symbol")
        _ov("Sector",   "icb_name3", "icb_name2", "sector")
        _ov("Exchange", "exchange",  "listing_exchange")

        for key in ("issue_share", "outstanding_shares"):
            v = ov.get(key)
            if v and str(v) not in ("nan",""):
                try:
                    ov_lines.append(f"  [bold]Shares Issued:[/bold] {int(float(v)):,}")
                    break
                except Exception:
                    pass

        for key in ("charter_capital",):
            v = ov.get(key)
            if v and str(v) not in ("nan",""):
                try:
                    ov_lines.append(f"  [bold]Charter Capital:[/bold] {_fmt_large(v)}")
                    break
                except Exception:
                    pass

        profile = str(ov.get("company_profile", ov.get("business_model", ""))).strip()
        if profile and profile != "nan":
            sentence = profile.split(".")[0].strip()
            if sentence:
                ov_lines.append(f"  [bold]About:[/bold] {sentence[:120]}")

    if ov_lines:
        console.print(Panel("\n".join(ov_lines), title="🏢 Company Overview", border_style="blue"))

    # ── Price ─────────────────────────────────────────────────────────────
    if price_df is not None and not price_df.empty:
        last   = float(price_df["close"].iloc[-1])
        prev   = float(price_df["close"].iloc[-2]) if len(price_df) > 1 else last
        chg    = (last - prev) / prev * 100 if prev else 0
        color  = "green" if chg >= 0 else "red"

        pt = Table(title="📊 Price Summary", box=box.SIMPLE_HEAVY)
        pt.add_column("Metric", style="bold"); pt.add_column("Value", justify="right")
        pt.add_row("Close",          f"{last:,.1f}")
        pt.add_row("Daily Change",   f"[{color}]{chg:+.2f}%[/{color}]")
        pt.add_row(f"{days}D High",  f"{price_df['high'].max():,.1f}")
        pt.add_row(f"{days}D Low",   f"{price_df['low'].min():,.1f}")
        pt.add_row("Avg Vol",        f"{price_df['volume'].mean():,.0f}")
        console.print(pt)

    # ── Ratios ────────────────────────────────────────────────────────────
    if ratios:
        rt = Table(title="📐 Key Ratios", box=box.SIMPLE_HEAVY)
        rt.add_column("Metric", style="bold"); rt.add_column("Value", justify="right")
        LABELS = {"pe":"P/E","pb":"P/B","roe":"ROE %","roa":"ROA %",
                  "eps":"EPS (VND)","net_margin":"Net Margin %","dividend_yield":"Div. Yield %"}
        for k, v in ratios.items():
            if k in ("roe","roa","net_margin","dividend_yield"):
                pct = v * 100 if abs(v) < 5 else v
                display = f"{pct:.2f}%"
            elif k == "eps":
                display = f"{int(v):,}"
            elif k in ("pe","pb"):
                display = f"{v:.2f}x"
            else:
                display = str(v)
            rt.add_row(LABELS.get(k, k.upper()), display)
        console.print(rt)

    # ── Technical Signals ─────────────────────────────────────────────────
    if tech_signals:
        tt = Table(title="📈 Technical Signals", box=box.SIMPLE_HEAVY)
        tt.add_column("Indicator", style="bold"); tt.add_column("Value", justify="right"); tt.add_column("Signal")
        SIG_COLOR = {"BUY":"green","SELL":"red","NEUTRAL":"yellow"}
        rows = [
            ("RSI (14)",   f"{tech_signals.get('rsi_14','')}", tech_signals.get("rsi_signal","")),
            ("MACD",       f"{tech_signals.get('macd_histogram',''):.4f}", tech_signals.get("macd_signal","")),
            ("EMA 9/21",   f"{tech_signals.get('ema_9','')} / {tech_signals.get('ema_21','')}", tech_signals.get("ema_trend","")),
            ("BB",         "",  tech_signals.get("bb_signal","")),
        ]
        for name, val, sig in rows:
            c = SIG_COLOR.get(sig, "white")
            tt.add_row(name, val, f"[{c}]{sig}[/{c}]")
        console.print(tt)

    # ── News ──────────────────────────────────────────────────────────────
    if news_list:
        nt = Table(title="📰 Latest News", box=box.SIMPLE_HEAVY, show_lines=True)
        nt.add_column("Date",   style="dim",  width=12)
        nt.add_column("Title",                width=68)
        nt.add_column("Source", style="cyan", width=16)
        for item in news_list[:5]:
            nt.add_row(
                str(item.get("published_date",""))[:10],
                str(item.get("title",""))[:80],
                str(item.get("source","")),
            )
        console.print(nt)
    else:
        console.print("  [dim]No news available.[/dim]")

    console.rule(style="cyan")


# ═════════════════════════════════════════════════════════════════════════════
# Company Snapshot — main entry point
# ═════════════════════════════════════════════════════════════════════════════

def get_company_snapshot(
    symbol: str,
    source: str = "VCI",
    days: int = 30,
    open_chart: bool = False,
    output_dir: str = ".",
) -> dict:
    client = DataClient(symbol=symbol, source=source)

    # Data collection
    price_df    = client.get_price_history(_days_ago(days), _today())
    overview_df = client.get_overview()
    ratios_df   = client.get_ratios()
    news_df     = client.get_news(limit=5)

    # Ratio extraction (battle-tested substrings from v1)
    ratios = _extract_ratios(ratios_df)

    # News cleaning
    news_list = _clean_news(news_df, limit=5)

    # Technical analysis
    tech_signals = None
    if not price_df.empty:
        try:
            ta = TechnicalAnalyzer(price_df)
            tech_signals = ta.get_signals()
        except Exception as e:
            console.log(f"  [yellow]⚠ TA skipped: {e}[/yellow]")

    # Print to terminal
    _print_snapshot(symbol, overview_df, price_df, ratios, news_list, tech_signals, days=days)

    # Export chart
    chart_path = _export_chart(price_df, symbol, output_dir)
    if chart_path and open_chart:
        import webbrowser
        webbrowser.open(f"file://{Path(chart_path).resolve()}")

    return {
        "symbol":      symbol,
        "overview":    overview_df,
        "price_df":    price_df,
        "ratios":      ratios,
        "tech":        tech_signals,
        "news":        news_list,
        "chart_path":  chart_path,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Full Pipeline — multiple tickers with Piotroski + Consensus
# ═════════════════════════════════════════════════════════════════════════════

def run_full_analysis(
    symbols: list[str],
    source: str = "VCI",
    days: int = 30,
    output_dir: str = ".",
    export_csv: bool = False,
) -> pd.DataFrame:
    console.rule("[bold magenta]🚀 Full Analysis Pipeline[/bold magenta]")
    results = []

    for symbol in symbols:
        console.print(f"\n[bold cyan]▶ Analyzing: {symbol}[/bold cyan]")
        row = {"symbol": symbol, "error": None}

        try:
            client = DataClient(symbol=symbol, source=source)

            price_df  = client.get_price_history(_days_ago(days*3), _today())
            ratios_df = client.get_ratios()
            balance_df= client.get_balance_sheet()
            income_df = client.get_income_statement()

            ratios = _extract_ratios(ratios_df)
            row.update({f"ratio_{k}": v for k, v in ratios.items()})

            # Technical
            if not price_df.empty:
                ta = TechnicalAnalyzer(price_df)
                sig = ta.get_signals()
                row.update({
                    "price":       sig["current_price"],
                    "rsi_14":      sig["rsi_14"],
                    "rsi_signal":  sig["rsi_signal"],
                    "macd_signal": sig["macd_signal"],
                    "ema_trend":   sig["ema_trend"],
                    "tech_score":  ta.score(),
                })
                tech_score = ta.score()
            else:
                tech_score = 0.0

            # Fundamental
            fa = FundamentalAnalyzer(ratios_df, balance_df, income_df)
            row.update({
                "piotroski_f": fa.score(),
                "fund_grade":  fa.grade(),
                "fund_score":  fa.score_normalized(),
            })

            # Consensus
            engine = ConsensusEngine(tech_score, fa.score_normalized(), symbol)
            s = engine.summary()
            row.update({"composite": s["composite"], "recommendation": s["recommendation"]})

        except Exception as e:
            row["error"] = str(e)
            console.print(f"  [red]❌ {symbol}: {e}[/red]")

        results.append(row)

    df = pd.DataFrame(results)

    # Summary table
    if not df.empty:
        console.rule("[bold]📋 Pipeline Summary[/bold]")
        st = Table(title="Consensus Recommendations", box=box.HEAVY_EDGE)
        cols = ["symbol","price","rsi_14","rsi_signal","macd_signal",
                "ema_trend","piotroski_f","fund_grade","composite","recommendation"]
        for c in cols:
            if c in df.columns: st.add_column(c.replace("_"," ").title())
        for _, r in df.iterrows():
            rec = str(r.get("recommendation",""))
            col = "green" if "BUY" in rec else ("red" if "SELL" in rec else "yellow")
            st.add_row(*[
                f"[{col}]{r[c]}[/{col}]" if c == "recommendation" else str(r.get(c,""))
                for c in cols if c in df.columns
            ])
        console.print(st)

    if export_csv and not df.empty:
        p = Path(output_dir) / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        df.to_csv(p, index=False, encoding="utf-8-sig")
        console.print(f"[green]✅ Saved → {p}[/green]")

    return df


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Platform v2")
    parser.add_argument("--symbol",     default="VCB")
    parser.add_argument("--symbols",    nargs="+")
    parser.add_argument("--source",     default="VCI")
    parser.add_argument("--days",       type=int, default=30)
    parser.add_argument("--open-chart", action="store_true")
    parser.add_argument("--export-csv", action="store_true")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    if args.symbols:
        run_full_analysis(
            args.symbols,
            source=args.source,
            days=args.days,
            output_dir=args.output_dir,
            export_csv=args.export_csv,
        )
    else:
        get_company_snapshot(
            symbol=args.symbol.upper(),
            source=args.source,
            days=args.days,
            open_chart=args.open_chart,
            output_dir=args.output_dir,
        )
