"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           VnStock Analysis Platform — Vietnam Stock Market                 ║
║           Built with: vnstock (formerly vnstock3, renamed Jan 2025)        ║
║           Author:  Senior Python Financial Engineer                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

Architecture:
  ┌─────────────────┐    ┌──────────────────────┐    ┌───────────────────────┐
  │   DataClient    │───▶│  TechnicalAnalyzer   │───▶│  FundamentalAnalyzer  │
  │  (Collection)   │    │  RSI / MACD / EMA    │    │  Health Score / DCF   │
  └─────────────────┘    └──────────────────────┘    └───────────────────────┘
           │                        │                           │
           └────────────────────────┴───────────────────────────┘
                                    │
                          ┌─────────▼────────┐
                          │  ConsensusEngine  │
                          │  Buy/Hold/Sell    │
                          └──────────────────┘
"""

import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Load API key from .env ───────────────────────────────────────────────────
from vnstock_auth import ensure_api_key, get_vnstock
ensure_api_key()

# ── Rich for beautiful terminal output ────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def _print(msg: str, style: str = ""):
    if RICH_AVAILABLE:
        console.print(msg, style=style)
    else:
        print(msg)


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 1: DataClient — All data collection in one place
# ══════════════════════════════════════════════════════════════════════════════

class DataClient:
    """
    Central data collection hub for Vietnamese stock market data.

    Wraps the vnstock library's Vnstock() entry-point and provides
    typed, documented methods for price, fundamental, and news data.

    Usage:
        client = DataClient(symbol='VCB', source='VCI')
        prices = client.get_price_history(interval='1D')
        ratios = client.get_financial_ratios()
        news   = client.get_news(limit=5)
    """

    # Supported intervals for quote.history()
    VALID_INTERVALS = {'1m', '5m', '15m', '30m', '1H', '4H', '1D', '1W', '1M'}

    def __init__(
        self,
        symbol: str,
        source: str = "VCI",
        years_back: int = 2,
    ):
        """
        Args:
            symbol    : Ticker symbol, e.g. 'VCB', 'FPT', 'HPG'
            source    : Data source — 'VCI' (default), 'TCBS', 'KBS', 'SSI'
            years_back: Number of years of historical data to fetch by default
        """
        self.symbol = symbol.upper()
        self.source = source
        self.years_back = years_back
        self._end_date = datetime.today().strftime("%Y-%m-%d")
        self._start_date = (
            datetime.today() - timedelta(days=365 * years_back)
        ).strftime("%Y-%m-%d")

        # Lazy-load Vnstock to surface import errors clearly
        try:
            self._stock = get_vnstock(self.symbol, source=self.source)
        except ImportError as exc:
            raise ImportError(
                "vnstock is not installed. Run: pip install vnstock"
            ) from exc

    # ── Price & Quote ──────────────────────────────────────────────────────────

    def get_price_history(
        self,
        interval: str = "1D",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV historical price data.

        Args:
            interval : Candle size — '1m','5m','15m','30m','1H','4H','1D','1W','1M'
            start    : ISO date string 'YYYY-MM-DD' (defaults to years_back ago)
            end      : ISO date string 'YYYY-MM-DD' (defaults to today)

        Returns:
            DataFrame with columns: time, open, high, low, close, volume
        """
        if interval not in self.VALID_INTERVALS:
            raise ValueError(
                f"Invalid interval '{interval}'. Choose from: {self.VALID_INTERVALS}"
            )
        start = start or self._start_date
        end = end or self._end_date

        _print(
            f"  📊 Fetching price history [{self.symbol}] {start} → {end} ({interval})",
            style="dim",
        )
        df = self._stock.quote.history(start=start, end=end, interval=interval)
        df.columns = [c.lower() for c in df.columns]
        return df

    def get_intraday(self, page_size: int = 10_000) -> pd.DataFrame:
        """Fetch tick-level intraday trades."""
        return self._stock.quote.intraday(
            symbol=self.symbol, page_size=page_size, show_log=False
        )

    # ── Fundamental Data ──────────────────────────────────────────────────────

    def get_company_overview(self) -> pd.DataFrame:
        """Company profile: name, sector, industry, exchange, listing date."""
        _print(f"  🏢 Fetching company overview [{self.symbol}]", style="dim")
        return self._stock.company.overview()

    def get_income_statement(self, period: str = "year", lang: str = "en") -> pd.DataFrame:
        """
        Fetch income statement.

        Args:
            period : 'year' or 'quarter'
            lang   : 'en' (English) or 'vi' (Vietnamese)
        """
        _print(f"  📋 Fetching income statement [{self.symbol}]", style="dim")
        return self._stock.finance.income_statement(period=period, lang=lang)

    def get_balance_sheet(self, period: str = "year", lang: str = "en") -> pd.DataFrame:
        """Fetch balance sheet (assets, liabilities, equity)."""
        _print(f"  📋 Fetching balance sheet [{self.symbol}]", style="dim")
        df = self._stock.finance.balance_sheet(period=period, lang=lang)
        return self._flatten_columns(df)

    def get_cash_flow(self, period: str = "year", lang: str = "en") -> pd.DataFrame:
        """Fetch cash flow statement."""
        _print(f"  📋 Fetching cash flow [{self.symbol}]", style="dim")
        df = self._stock.finance.cash_flow(period=period, lang=lang)
        return self._flatten_columns(df)

    @staticmethod
    def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Flatten MultiIndex or tuple columns to plain strings."""
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

    def get_financial_ratios(self, period: str = "year") -> pd.DataFrame:
        """
        Fetch key financial ratios: P/E, P/B, ROE, ROA, EPS, debt ratios, etc.

        Args:
            period : 'year' or 'quarter'
        """
        _print(f"  📐 Fetching financial ratios [{self.symbol}]", style="dim")
        df = self._stock.finance.ratio(period=period, lang="en")
        # Flatten MultiIndex / tuple columns returned by some vnstock sources
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

    # ── News & Sentiment ──────────────────────────────────────────────────────

    def get_news(self, limit: int = 10) -> pd.DataFrame:
        """
        Fetch the most recent company news.

        Args:
            limit : Number of news articles to return

        Returns:
            DataFrame with columns: published_date, title, source, url
        """
        _print(f"  📰 Fetching news [{self.symbol}]", style="dim")
        try:
            return self._stock.company.news(limit=limit)
        except Exception:
            # Fallback: some sources expose news differently
            try:
                from vnstock import Company
                return Company(symbol=self.symbol, source=self.source).news(limit=limit)
            except Exception as e:
                _print(f"  ⚠ News fetch failed: {e}", style="yellow")
                return pd.DataFrame(columns=["published_date", "title", "source"])

    def get_dividends(self) -> pd.DataFrame:
        """Fetch historical dividend payments."""
        _print(f"  💰 Fetching dividends [{self.symbol}]", style="dim")
        try:
            return self._stock.company.dividends()
        except Exception as e:
            _print(f"  ⚠ Dividends fetch failed: {e}", style="yellow")
            return pd.DataFrame()

    def get_shareholders(self) -> pd.DataFrame:
        """Fetch major shareholders."""
        _print(f"  👥 Fetching shareholders [{self.symbol}]", style="dim")
        try:
            return self._stock.company.shareholders()
        except Exception as e:
            _print(f"  ⚠ Shareholders fetch failed: {e}", style="yellow")
            return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 2: TechnicalAnalyzer — RSI, MACD, EMA
# ══════════════════════════════════════════════════════════════════════════════

class TechnicalAnalyzer:
    """
    Computes RSI, MACD, and EMA on a price DataFrame.

    Uses pandas-ta under the hood, which mirrors the vnstock_ta API
    while being dependency-light.

    Usage:
        analyzer = TechnicalAnalyzer(price_df)
        signals  = analyzer.get_signals()
        score    = analyzer.score()   # float in [-1, 1]
    """

    def __init__(self, price_df: pd.DataFrame):
        """
        Args:
            price_df : DataFrame from DataClient.get_price_history()
                       Must contain 'close', 'high', 'low', 'volume' columns.
        """
        if price_df is None or price_df.empty:
            raise ValueError("price_df is empty — cannot run technical analysis.")

        self.df = price_df.copy().sort_values("time").reset_index(drop=True)

        # Ensure numeric close column
        self.df["close"] = pd.to_numeric(self.df["close"], errors="coerce")
        self.df.dropna(subset=["close"], inplace=True)

        self._indicators: Optional[pd.DataFrame] = None

    def _compute_indicators(self) -> pd.DataFrame:
        """Lazy-compute RSI, MACD, and EMA bands. Cached after first call."""
        if self._indicators is not None:
            return self._indicators

        df = self.df.copy()
        close = df["close"]

        # ── RSI (14-period) ──────────────────────────────────
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # ── EMA bands ────────────────────────────────────────
        df["ema_9"]  = close.ewm(span=9,  adjust=False).mean()
        df["ema_21"] = close.ewm(span=21, adjust=False).mean()
        df["ema_50"] = close.ewm(span=50, adjust=False).mean()
        df["ema_200"]= close.ewm(span=200, adjust=False).mean()

        # ── MACD (12-26-9) ────────────────────────────────────
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["macd_line"]   = ema12 - ema26
        df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
        df["macd_hist"]   = df["macd_line"] - df["macd_signal"]

        # ── Bollinger Bands (20, 2σ) ──────────────────────────
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        df["bb_upper"] = sma20 + 2 * std20
        df["bb_lower"] = sma20 - 2 * std20
        df["bb_mid"]   = sma20

        self._indicators = df
        return df

    def get_signals(self) -> dict:
        """
        Derive Buy/Sell/Neutral signals from the latest indicator values.

        Returns a dict with keys:
            rsi_signal, macd_signal, ema_trend, bb_signal,
            current_price, rsi_14, macd_histogram
        """
        df = self._compute_indicators()
        latest = df.iloc[-1]

        signals = {
            "current_price": round(float(latest["close"]), 2),
            "rsi_14": round(float(latest.get("rsi_14", np.nan)), 2),
            "macd_histogram": round(float(latest.get("macd_hist", np.nan)), 4),
            "ema_9": round(float(latest.get("ema_9", np.nan)), 2),
            "ema_21": round(float(latest.get("ema_21", np.nan)), 2),
            "ema_50": round(float(latest.get("ema_50", np.nan)), 2),
            "ema_200": round(float(latest.get("ema_200", np.nan)), 2),
        }

        # RSI signal
        rsi = signals["rsi_14"]
        if np.isnan(rsi):
            signals["rsi_signal"] = "NEUTRAL"
        elif rsi < 30:
            signals["rsi_signal"] = "BUY"        # Oversold
        elif rsi > 70:
            signals["rsi_signal"] = "SELL"       # Overbought
        else:
            signals["rsi_signal"] = "NEUTRAL"

        # MACD signal
        hist = signals["macd_histogram"]
        prev_hist = float(df.iloc[-2].get("macd_hist", np.nan)) if len(df) > 1 else np.nan
        if np.isnan(hist) or np.isnan(prev_hist):
            signals["macd_signal"] = "NEUTRAL"
        elif hist > 0 and prev_hist <= 0:
            signals["macd_signal"] = "BUY"        # Bullish crossover
        elif hist < 0 and prev_hist >= 0:
            signals["macd_signal"] = "SELL"       # Bearish crossover
        elif hist > 0:
            signals["macd_signal"] = "BUY"
        else:
            signals["macd_signal"] = "SELL"

        # EMA trend (9 vs 21 crossover)
        e9, e21 = signals["ema_9"], signals["ema_21"]
        if np.isnan(e9) or np.isnan(e21):
            signals["ema_trend"] = "NEUTRAL"
        elif e9 > e21:
            signals["ema_trend"] = "BUY"          # Short-term uptrend
        else:
            signals["ema_trend"] = "SELL"

        # Bollinger Band signal
        price = signals["current_price"]
        bb_up = float(latest.get("bb_upper", np.nan))
        bb_lo = float(latest.get("bb_lower", np.nan))
        if np.isnan(bb_up) or np.isnan(bb_lo):
            signals["bb_signal"] = "NEUTRAL"
        elif price >= bb_up:
            signals["bb_signal"] = "SELL"
        elif price <= bb_lo:
            signals["bb_signal"] = "BUY"
        else:
            signals["bb_signal"] = "NEUTRAL"

        return signals

    def score(self) -> float:
        """
        Aggregate technical signals into a score in range [-1.0, +1.0].
        Positive = bullish bias, Negative = bearish bias.
        """
        signals = self.get_signals()
        SIGNAL_MAP = {"BUY": 1, "NEUTRAL": 0, "SELL": -1}
        raw = [
            SIGNAL_MAP.get(signals["rsi_signal"],  0) * 1.5,  # RSI weighted more
            SIGNAL_MAP.get(signals["macd_signal"], 0) * 1.5,  # MACD weighted more
            SIGNAL_MAP.get(signals["ema_trend"],   0) * 1.0,
            SIGNAL_MAP.get(signals["bb_signal"],   0) * 0.5,
        ]
        return round(sum(raw) / 4.5, 4)    # Normalize to [-1, 1]

    def get_dataframe(self) -> pd.DataFrame:
        """Return the full DataFrame with all indicators appended."""
        return self._compute_indicators()


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 3: FundamentalAnalyzer — Financial Health Score
# ══════════════════════════════════════════════════════════════════════════════

class FundamentalAnalyzer:
    """
    Scores a stock's financial health from 0 (poor) to 100 (excellent)
    using the Piotroski F-Score framework adapted for Vietnamese equities.

    Nine binary criteria across Profitability, Leverage, and Efficiency:

    Profitability (max 3):
        F1 — Positive ROA
        F2 — Positive Operating Cash Flow
        F3 — Increasing ROA (YoY)
        F4 — Accruals < 0 (cash earnings quality)

    Leverage & Liquidity (max 3):
        F5 — Decreasing Debt Ratio
        F6 — Increasing Current Ratio
        F7 — No dilution (shares outstanding stable/falling)

    Operating Efficiency (max 3):
        F8 — Increasing Gross Margin
        F9 — Increasing Asset Turnover

    Usage:
        fa = FundamentalAnalyzer(ratios_df, balance_df, income_df)
        score = fa.score()          # int in [0, 9]
        details = fa.get_details()  # dict with per-criterion scores
    """

    def __init__(
        self,
        ratios_df: pd.DataFrame,
        balance_df: pd.DataFrame,
        income_df: pd.DataFrame,
    ):
        self.ratios  = ratios_df
        self.balance = balance_df
        self.income  = income_df
        self._details: Optional[dict] = None

    def _safe_get(self, df: pd.DataFrame, col: str, row: int = 0) -> float:
        """Safely extract a numeric value from a DataFrame."""
        try:
            val = df[col].iloc[row]
            return float(val) if not pd.isna(val) else np.nan
        except (KeyError, IndexError):
            return np.nan

    def _find_col(self, df: pd.DataFrame, *candidates) -> Optional[str]:
        """Return the first matching column name from a list of candidates."""
        lower_cols = {c.lower(): c for c in df.columns}
        for c in candidates:
            if c.lower() in lower_cols:
                return lower_cols[c.lower()]
        return None

    def get_details(self) -> dict:
        """
        Evaluate all 9 Piotroski criteria.

        Returns:
            Dict mapping criterion label → {'score': int, 'value': float, 'note': str}
        """
        if self._details is not None:
            return self._details

        results = {}

        # ─────────────────── PROFITABILITY ──────────────────────────────────

        # F1: Positive ROA this year
        roa_col = self._find_col(self.ratios, "roa", "return_on_assets", "Return On Assets")
        roa_t0 = self._safe_get(self.ratios, roa_col) if roa_col else np.nan
        roa_t1 = self._safe_get(self.ratios, roa_col, 1) if roa_col else np.nan
        f1 = 1 if not np.isnan(roa_t0) and roa_t0 > 0 else 0
        results["F1_positive_roa"] = {
            "score": f1, "value": roa_t0,
            "note": "ROA > 0 (profitable asset deployment)"
        }

        # F2: Positive Operating Cash Flow
        ocf_col = self._find_col(self.income, "operating_cash_flow", "cfo", "cash_from_operations")
        ocf = self._safe_get(self.income, ocf_col) if ocf_col else np.nan
        f2 = 1 if not np.isnan(ocf) and ocf > 0 else 0
        results["F2_positive_ocf"] = {
            "score": f2, "value": ocf,
            "note": "Operating Cash Flow > 0"
        }

        # F3: Increasing ROA
        f3 = 1 if not np.isnan(roa_t0) and not np.isnan(roa_t1) and roa_t0 > roa_t1 else 0
        results["F3_roa_improving"] = {
            "score": f3, "value": roa_t0 - roa_t1 if not np.isnan(roa_t0) and not np.isnan(roa_t1) else np.nan,
            "note": "ROA increasing YoY"
        }

        # F4: Cash earnings quality (OCF > Net Income → accruals < 0 → quality)
        ni_col = self._find_col(self.income, "net_income", "net_profit", "profit_after_tax")
        ni = self._safe_get(self.income, ni_col) if ni_col else np.nan
        f4 = 1 if not np.isnan(ocf) and not np.isnan(ni) and ocf > ni else 0
        results["F4_accruals_quality"] = {
            "score": f4, "value": (ocf - ni) if not np.isnan(ocf) and not np.isnan(ni) else np.nan,
            "note": "OCF > Net Income (earnings backed by cash)"
        }

        # ─────────────────── LEVERAGE & LIQUIDITY ───────────────────────────

        # F5: Decreasing long-term debt ratio
        der_col = self._find_col(self.ratios, "debt_ratio", "debt_to_equity", "de_ratio")
        dr_t0 = self._safe_get(self.ratios, der_col) if der_col else np.nan
        dr_t1 = self._safe_get(self.ratios, der_col, 1) if der_col else np.nan
        f5 = 1 if not np.isnan(dr_t0) and not np.isnan(dr_t1) and dr_t0 < dr_t1 else 0
        results["F5_leverage_decreasing"] = {
            "score": f5, "value": dr_t0,
            "note": "Debt ratio lower than prior year"
        }

        # F6: Increasing current ratio
        cr_col = self._find_col(self.ratios, "current_ratio", "currentRatio")
        cr_t0 = self._safe_get(self.ratios, cr_col) if cr_col else np.nan
        cr_t1 = self._safe_get(self.ratios, cr_col, 1) if cr_col else np.nan
        f6 = 1 if not np.isnan(cr_t0) and not np.isnan(cr_t1) and cr_t0 > cr_t1 else 0
        results["F6_liquidity_improving"] = {
            "score": f6, "value": cr_t0,
            "note": "Current ratio improving YoY"
        }

        # F7: No share dilution (shares outstanding not increased)
        shares_col = self._find_col(self.balance, "shares_outstanding", "outstanding_shares")
        sh_t0 = self._safe_get(self.balance, shares_col) if shares_col else np.nan
        sh_t1 = self._safe_get(self.balance, shares_col, 1) if shares_col else np.nan
        f7 = 1 if np.isnan(sh_t0) or np.isnan(sh_t1) or sh_t0 <= sh_t1 else 0
        results["F7_no_dilution"] = {
            "score": f7, "value": sh_t0,
            "note": "Shares outstanding not increased"
        }

        # ─────────────────── OPERATING EFFICIENCY ───────────────────────────

        # F8: Improving gross margin
        gm_col = self._find_col(self.ratios, "gross_margin", "gross_profit_margin")
        gm_t0 = self._safe_get(self.ratios, gm_col) if gm_col else np.nan
        gm_t1 = self._safe_get(self.ratios, gm_col, 1) if gm_col else np.nan
        f8 = 1 if not np.isnan(gm_t0) and not np.isnan(gm_t1) and gm_t0 > gm_t1 else 0
        results["F8_gross_margin_up"] = {
            "score": f8, "value": gm_t0,
            "note": "Gross margin improving YoY"
        }

        # F9: Improving asset turnover
        at_col = self._find_col(self.ratios, "asset_turnover", "assetTurnover")
        at_t0 = self._safe_get(self.ratios, at_col) if at_col else np.nan
        at_t1 = self._safe_get(self.ratios, at_col, 1) if at_col else np.nan
        f9 = 1 if not np.isnan(at_t0) and not np.isnan(at_t1) and at_t0 > at_t1 else 0
        results["F9_asset_turnover_up"] = {
            "score": f9, "value": at_t0,
            "note": "Asset turnover improving YoY"
        }

        self._details = results
        return results

    def score(self) -> int:
        """Return Piotroski F-Score in range [0, 9]."""
        return sum(v["score"] for v in self.get_details().values())

    def score_normalized(self) -> float:
        """Return F-Score normalized to [-1.0, +1.0] for consensus engine."""
        raw = self.score()              # 0 to 9
        return round((raw / 9) * 2 - 1, 4)   # maps 0→-1, 4.5→0, 9→+1

    def grade(self) -> str:
        """Qualitative grade based on F-Score."""
        s = self.score()
        if s >= 8:   return "STRONG BUY  (F-Score 8-9)"
        if s >= 6:   return "BUY         (F-Score 6-7)"
        if s >= 4:   return "HOLD        (F-Score 4-5)"
        if s >= 2:   return "SELL        (F-Score 2-3)"
        return             "STRONG SELL (F-Score 0-1)"


# ══════════════════════════════════════════════════════════════════════════════
#  MODULE 4: ConsensusEngine — Final Buy/Hold/Sell aggregation
# ══════════════════════════════════════════════════════════════════════════════

class ConsensusEngine:
    """
    Aggregates technical and fundamental signals into a single recommendation.

    Weighting:
        Technical  : 40%
        Fundamental: 60%   (longer-term view dominates for VN equities)

    Output:
        STRONG BUY  → composite_score > +0.60
        BUY         → composite_score > +0.20
        HOLD        → composite_score in [-0.20, +0.20]
        SELL        → composite_score < -0.20
        STRONG SELL → composite_score < -0.60
    """

    TECHNICAL_WEIGHT   = 0.40
    FUNDAMENTAL_WEIGHT = 0.60

    def __init__(
        self,
        tech_score: float,
        fund_score: float,
        symbol: str,
    ):
        """
        Args:
            tech_score  : TechnicalAnalyzer.score()        → [-1, 1]
            fund_score  : FundamentalAnalyzer.score_normalized() → [-1, 1]
            symbol      : Ticker symbol (for display)
        """
        self.tech_score  = tech_score
        self.fund_score  = fund_score
        self.symbol      = symbol
        self.composite   = round(
            self.tech_score  * self.TECHNICAL_WEIGHT +
            self.fund_score  * self.FUNDAMENTAL_WEIGHT,
            4,
        )

    def recommendation(self) -> str:
        c = self.composite
        if c > 0.60:   return "STRONG BUY 🟢🟢"
        if c > 0.20:   return "BUY 🟢"
        if c >= -0.20: return "HOLD 🟡"
        if c >= -0.60: return "SELL 🔴"
        return               "STRONG SELL 🔴🔴"

    def summary(self) -> dict:
        return {
            "symbol":          self.symbol,
            "technical_score": self.tech_score,
            "fundamental_score": self.fund_score,
            "composite_score": self.composite,
            "recommendation":  self.recommendation(),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  TASK 2: Company Snapshot — Single-ticker quick-view
# ══════════════════════════════════════════════════════════════════════════════

def get_company_snapshot(symbol: str, source: str = "VCI") -> dict:
    """
    Fetch a complete Company Snapshot combining:
      - Current price & 30-day OHLCV summary
      - Company overview (sector, exchange)
      - Key financial ratios (P/E, P/B, ROE, EPS)
      - 5 most recent news articles

    Args:
        symbol : Ticker, e.g. 'VCB', 'FPT', 'HPG'
        source : Data source — 'VCI' (default) or 'TCBS'

    Returns:
        dict with keys: overview, price_summary, ratios, news
    """
    if RICH_AVAILABLE:
        console.rule(f"[bold cyan]📸 Company Snapshot: {symbol}[/bold cyan]")
    else:
        print(f"\n{'='*60}\n  Company Snapshot: {symbol}\n{'='*60}")

    client = DataClient(symbol=symbol, source=source)

    # ── 1. Company Overview ────────────────────────────────────────────────
    _print("\n[bold]① Company Overview[/bold]")
    try:
        overview_df = client.get_company_overview()
        overview = overview_df.iloc[0].to_dict() if not overview_df.empty else {}
    except Exception as e:
        _print(f"  ⚠ Overview unavailable: {e}", style="yellow")
        overview = {}

    # ── 2. Recent Price Data (30 calendar days) ────────────────────────────
    _print("\n[bold]② Price Summary (30 days)[/bold]")
    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=30)
    try:
        price_df = client.get_price_history(
            interval="1D",
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
        )
        if not price_df.empty:
            latest_close = float(price_df["close"].iloc[-1])
            prev_close   = float(price_df["close"].iloc[-2]) if len(price_df) > 1 else np.nan
            pct_change   = ((latest_close - prev_close) / prev_close * 100) if not np.isnan(prev_close) else np.nan
            price_summary = {
                "latest_close":  round(latest_close, 2),
                "prev_close":    round(prev_close, 2),
                "daily_chg_pct": round(pct_change, 2),
                "30d_high":      round(float(price_df["high"].max()), 2),
                "30d_low":       round(float(price_df["low"].min()), 2),
                "avg_volume_30d":int(price_df["volume"].mean()),
            }
        else:
            price_summary = {}
    except Exception as e:
        _print(f"  ⚠ Price data unavailable: {e}", style="yellow")
        price_summary = {}

    # ── 3. Financial Ratios ────────────────────────────────────────────────
    _print("\n[bold]③ Key Financial Ratios[/bold]")
    try:
        ratios_df = client.get_financial_ratios(period="year")
        col_lower = {c.lower(): c for c in ratios_df.columns}

        # Exact substrings confirmed from DEBUG output (vnstock VCI source)
        key_targets = {
            "pe":            ["định giá_p/e",  "p/e",  "pricetoearning", "price_to_earning", "ratio_pe"],
            "pb":            ["định giá_p/b",  "p/b",  "pricetobook",    "price_to_book",    "ratio_pb"],
            "roe":           ["sinh lợi_roe",  "roe",  "return_on_equity"],
            "roa":           ["sinh lợi_roa",  "roa",  "return_on_assets"],
            "eps":           ["định giá_eps",  "eps",  "earning_per_share"],
            "net_margin":    ["net profit margin", "net_profit_margin", "profit_margin"],
            "dividend_yield":["dividend yield",    "dividend_yield"],
        }
        ratios = {}
        for label, substrings in key_targets.items():
            for sub in substrings:
                for col_l, col_orig in col_lower.items():
                    if sub in col_l:
                        try:
                            val = ratios_df[col_orig].iloc[0]
                            if not pd.isna(val):
                                ratios[label] = round(float(val), 4)
                        except Exception:
                            pass
                        break
                if label in ratios:
                    break

        if not ratios:
            _print(f"  ⚠ Could not map ratio columns. Available: {list(ratios_df.columns[:10])}", style="yellow")

    except Exception as e:
        _print(f"  ⚠ Ratios unavailable: {e}", style="yellow")
        ratios = {}

    # ── 4. Recent News ─────────────────────────────────────────────────────
    _print("\n[bold]④ Latest News (5 articles)[/bold]")
    news_df = client.get_news(limit=5)
    if not news_df.empty:
        import re as _re
        cols = list(news_df.columns)

        # ── Direct exact-name mapping for confirmed vnstock VCI columns ──────
        # Falls back to fuzzy matching for other sources
        EXACT_MAP = {
            "public_date":      "published_date",   # Unix ms timestamp
            "news_title":       "title",
            "news_source_link": "source",
        }
        col_remap = {}
        for c in cols:
            if c in EXACT_MAP:
                col_remap[c] = EXACT_MAP[c]

        # Fuzzy fallback for any target still unmapped
        mapped_targets = set(col_remap.values())
        DATE_KEYS   = ["publish_date", "publishdate", "public_date", "date", "ngay"]
        TITLE_KEYS  = ["news_title", "title", "tieu", "headline"]
        SOURCE_KEYS = ["news_source_link", "source_link", "source", "nguon"]

        for c in cols:
            if c in col_remap:
                continue
            cl = c.lower()
            if "published_date" not in mapped_targets and any(k in cl for k in DATE_KEYS):
                col_remap[c] = "published_date"
                mapped_targets.add("published_date")
            elif "title" not in mapped_targets and any(k in cl for k in TITLE_KEYS):
                col_remap[c] = "title"
                mapped_targets.add("title")
            elif "source" not in mapped_targets and any(k in cl for k in SOURCE_KEYS):
                col_remap[c] = "source"
                mapped_targets.add("source")

        news_df = news_df.rename(columns=col_remap)

        # ── Clean title: strip HTML tags ────────────────────────────────────
        if "title" in news_df.columns:
            if isinstance(news_df["title"], pd.DataFrame):
                news_df = news_df.loc[:, ~news_df.columns.duplicated()]
            news_df["title"] = news_df["title"].astype(str).apply(
                lambda x: _re.sub(r"<[^>]+>", "", x).strip()
            )

        # ── Clean date: handle Unix ms timestamp or ISO string ───────────────
        if "published_date" in news_df.columns:
            def _parse_date(val):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return ""
                try:
                    v = float(val)
                    if v > 1e10:             # Unix milliseconds (e.g. 1774637744000)
                        v = v / 1000
                    return datetime.fromtimestamp(v).strftime("%Y-%m-%d")
                except Exception:
                    s = str(val).strip()
                    return s[:10] if s not in ("nan", "None", "NaT") else ""
            news_df["published_date"] = news_df["published_date"].apply(_parse_date)

        # ── Clean source: shorten URL to domain only ─────────────────────────
        if "source" in news_df.columns:
            news_df["source"] = news_df["source"].astype(str).apply(
                lambda x: x.replace("https://", "").replace("http://", "").split("/")[0]
                if x.startswith("http") else x
            )

        # Ensure all required columns exist
        for col in ["published_date", "title", "source"]:
            if col not in news_df.columns:
                news_df[col] = ""

    news_list = news_df.to_dict("records") if not news_df.empty else []

    # ── Print Summary ──────────────────────────────────────────────────────
    _print_snapshot(symbol, overview, price_summary, ratios, news_list)

    return {
        "symbol":        symbol,
        "overview":      overview,
        "price_summary": price_summary,
        "ratios":        ratios,
        "news":          news_list,
    }


def _print_snapshot(symbol, overview, price_summary, ratios, news_list):
    """Render the snapshot to the terminal."""
    if not RICH_AVAILABLE:
        print(f"\n  [Overview] {overview}")
        print(f"  [Price]    {price_summary}")
        print(f"  [Ratios]   {ratios}")
        print(f"  [News]     {len(news_list)} articles loaded")
        return

    # ── Overview Panel ─────────────────────────────────────────────────────
    # vnstock VCI overview only returns: symbol, id, issue_share, history,
    # company_profile, icb_name2/3/4, financial_ratio_issue_share, charter_capital
    ov_lines = []
    def _ov(label, key, fmt=None):
        v = overview.get(key)
        if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan"):
            return
        text = fmt(v) if fmt else str(v)
        if len(text) > 120:
            text = text[:117] + "..."
        ov_lines.append(f"  [bold]{label}[/bold]: {text}")

    _ov("Ticker",          "symbol")
    _ov("Sector",          "icb_name3")
    _ov("Shares Issued",   "issue_share",
        fmt=lambda v: f"{int(float(v)):,}")
    _ov("Charter Capital", "charter_capital",
        fmt=lambda v: f"{int(float(v)) / 1_000_000_000_000:.2f} trillion VND")

    # Extract first sentence of company_profile as a short description
    profile = str(overview.get("company_profile", "")).strip()
    if profile and profile != "nan":
        first_sentence = profile.split(".")[0].strip()
        if first_sentence:
            ov_lines.append(f"  [bold]About[/bold]: {first_sentence[:120]}")

    ov_text = "\n".join(ov_lines) or "  No data available."
    console.print(Panel(ov_text, title="🏢 Company Overview", border_style="blue"))

    # ── Price Table ────────────────────────────────────────────────────────
    if price_summary:
        pt = Table(title="📊 Price Summary", box=box.SIMPLE_HEAVY)
        pt.add_column("Metric", style="bold")
        pt.add_column("Value",  justify="right")
        change_color = "green" if price_summary.get("daily_chg_pct", 0) >= 0 else "red"
        pt.add_row("Close",         f"{price_summary.get('latest_close', 'N/A'):,}")
        pt.add_row("Daily Change",  f"[{change_color}]{price_summary.get('daily_chg_pct', 'N/A')}%[/]")
        pt.add_row("30-Day High",   f"{price_summary.get('30d_high', 'N/A'):,}")
        pt.add_row("30-Day Low",    f"{price_summary.get('30d_low', 'N/A'):,}")
        pt.add_row("Avg Vol (30D)", f"{price_summary.get('avg_volume_30d', 'N/A'):,}")
        console.print(pt)

    # ── Ratios Table ───────────────────────────────────────────────────────
    if ratios:
        rt = Table(title="📐 Key Ratios", box=box.SIMPLE_HEAVY)
        rt.add_column("Metric", style="bold")
        rt.add_column("Value",  justify="right")
        LABELS = {
            "pe":  "P/E", "pb": "P/B",
            "roe": "ROE %", "roa": "ROA %",
            "eps": "EPS (VND)", "net_margin": "Net Margin %",
            "dividend_yield": "Div. Yield %",
            "current_ratio": "Current Ratio", "debt_ratio": "Debt Ratio",
        }
        for k, v in ratios.items():
            if k in ("roe", "roa", "net_margin", "dividend_yield"):
                # VCI stores as decimal (0.1673) despite "(%" in column name
                # Heuristic: if abs < 5 it's decimal form → multiply by 100
                pct = v * 100 if abs(v) < 5 else v
                display = f"{pct:.2f}%"
            elif k == "eps":
                display = f"{int(v):,}"
            elif k in ("pe", "pb"):
                display = f"{v:.2f}x"
            elif k in ("current_ratio", "debt_ratio"):
                display = f"{v:.2f}"
            else:
                display = str(v)
            rt.add_row(LABELS.get(k, k.upper()), display)
        console.print(rt)

    # ── News ───────────────────────────────────────────────────────────────
    if news_list:
        nt = Table(title="📰 Latest News", box=box.SIMPLE_HEAVY, show_lines=True)
        nt.add_column("Date",  style="dim", width=12)
        nt.add_column("Title")
        nt.add_column("Source", style="cyan", width=14)
        for item in news_list[:5]:
            nt.add_row(
                str(item.get("published_date", ""))[:10],
                str(item.get("title", ""))[:80],
                str(item.get("source", "")),
            )
        console.print(nt)
    else:
        console.print("  [dim]No news available.[/dim]")


# ══════════════════════════════════════════════════════════════════════════════
#  Full Pipeline Runner — all three modules for a list of tickers
# ══════════════════════════════════════════════════════════════════════════════

def run_full_analysis(symbols: list[str], source: str = "VCI") -> pd.DataFrame:
    """
    Run the complete pipeline (Data → Technical → Fundamental → Consensus)
    for a list of ticker symbols.

    Args:
        symbols : List of ticker strings, e.g. ['VCB', 'FPT', 'HPG']
        source  : Data source to use across all tickers

    Returns:
        DataFrame with one row per ticker containing all scores and recommendations
    """
    if RICH_AVAILABLE:
        console.rule("[bold magenta]🚀 Full Analysis Pipeline[/bold magenta]")

    results = []

    for symbol in symbols:
        _print(f"\n[bold cyan]▶ Analyzing: {symbol}[/bold cyan]")

        row = {"symbol": symbol, "error": None}

        try:
            # 1. Collect all data
            client = DataClient(symbol=symbol, source=source, years_back=3)

            price_df  = client.get_price_history(interval="1D")
            ratios_df = client.get_financial_ratios(period="year")
            balance_df= client.get_balance_sheet(period="year")
            income_df = client.get_income_statement(period="year")

            # 2. Technical analysis
            ta = TechnicalAnalyzer(price_df)
            tech_signals = ta.get_signals()
            tech_score   = ta.score()
            row.update({
                "price":        tech_signals["current_price"],
                "rsi_14":       tech_signals["rsi_14"],
                "macd_hist":    tech_signals["macd_histogram"],
                "rsi_signal":   tech_signals["rsi_signal"],
                "macd_signal":  tech_signals["macd_signal"],
                "ema_trend":    tech_signals["ema_trend"],
                "tech_score":   tech_score,
            })

            # 3. Fundamental analysis
            fa = FundamentalAnalyzer(ratios_df, balance_df, income_df)
            fund_raw    = fa.score()
            fund_score  = fa.score_normalized()
            fund_grade  = fa.grade()
            row.update({
                "piotroski_f": fund_raw,
                "fund_grade":  fund_grade,
                "fund_score":  fund_score,
            })

            # 4. Consensus
            engine = ConsensusEngine(tech_score, fund_score, symbol)
            summary = engine.summary()
            row.update({
                "composite_score": summary["composite_score"],
                "recommendation":  summary["recommendation"],
            })

        except Exception as e:
            row["error"] = str(e)
            _print(f"  ❌ Error for {symbol}: {e}", style="red")

        results.append(row)

    df_results = pd.DataFrame(results)

    # Print summary table
    if RICH_AVAILABLE and not df_results.empty:
        console.rule("[bold]📋 Analysis Summary[/bold]")
        st = Table(title="Consensus Recommendations", box=box.HEAVY_EDGE)
        for col in ["symbol","price","rsi_14","rsi_signal","macd_signal",
                    "ema_trend","piotroski_f","fund_grade","composite_score","recommendation"]:
            if col in df_results.columns:
                st.add_column(col.replace("_"," ").title())
        for _, r in df_results.iterrows():
            rec = str(r.get("recommendation", ""))
            color = "green" if "BUY" in rec else ("red" if "SELL" in rec else "yellow")
            st.add_row(*[
                f"[{color}]{r[col]}[/]" if col == "recommendation" else str(r.get(col,""))
                for col in ["symbol","price","rsi_14","rsi_signal","macd_signal",
                            "ema_trend","piotroski_f","fund_grade","composite_score","recommendation"]
                if col in df_results.columns
            ])
        console.print(st)

    return df_results


# ══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ─── Task 2: Company Snapshot Demo ────────────────────────────────────
    snapshot = get_company_snapshot("VCB", source="VCI")

    # ─── Full Pipeline: Three blue-chip VN stocks ─────────────────────────
    # Uncomment to run:
    # results_df = run_full_analysis(["VCB", "FPT", "HPG"], source="VCI")
    # results_df.to_csv("vnstock_analysis_results.csv", index=False)
    # print("\n✅ Results saved to vnstock_analysis_results.csv")
