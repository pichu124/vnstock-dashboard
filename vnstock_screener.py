"""
vnstock_screener.py — Market-wide Stock Screener
=================================================
Lọc cổ phiếu toàn thị trường từ local Parquet warehouse.
Không gọi API — chạy trên ~3000 mã trong vài phút.

Run:
  python vnstock_screener.py                          # Preset mặc định
  python vnstock_screener.py --preset oversold        # RSI < 30
  python vnstock_screener.py --preset momentum        # MACD bullish + uptrend
  python vnstock_screener.py --preset value           # P/E thấp + ROE cao
  python vnstock_screener.py --top 20                 # Hiện top 20
  python vnstock_screener.py --export                 # Xuất CSV
"""

import argparse
import os
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from rich import box
from rich.console import Console
from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn)
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()


# ═════════════════════════════════════════════════════════════════════════════
# Industry map — đọc từ classifier warehouse
# ═════════════════════════════════════════════════════════════════════════════

def _load_fundamentals(warehouse_root: str = "data_warehouse"):
    """Load bảng P/E, ROE từ warehouse nếu có."""
    path = Path(warehouse_root) / "_meta" / "fundamentals.parquet"
    if not path.exists():
        return None
    try:
        import pyarrow.parquet as _pq
        df = _pq.read_table(str(path)).to_pandas()
        return df.set_index("ticker")
    except Exception:
        return None


def _calc_industry_medians(fund_df, warehouse_root: str = "data_warehouse") -> dict:
    """Tính median P/E, ROE cho từng ngành từ fundamentals."""
    if fund_df is None or fund_df.empty:
        return {}
    industry_path = Path(warehouse_root) / "_meta" / "industry_classification.parquet"
    if not industry_path.exists():
        return {}
    try:
        import pyarrow.parquet as _pq
        ind_df = _pq.read_table(
            str(industry_path), columns=["ticker", "primary_industry"]
        ).to_pandas().rename(columns={"primary_industry": "industry"})
    except Exception:
        return {}
    merged = fund_df.reset_index().merge(ind_df, on="ticker", how="left")
    merged["industry"] = merged["industry"].fillna("Khác")
    medians = {}
    for industry, grp in merged.groupby("industry"):
        medians[industry] = {
            "pe":  float(grp["pe"].dropna().median())  if "pe"  in grp.columns else float("nan"),
            "roe": float(grp["roe"].dropna().median()) if "roe" in grp.columns else float("nan"),
        }
    return medians


def _load_industry_map(warehouse_root: str = "data_warehouse") -> dict:
    """
    Đọc kết quả phân loại ngành từ classifier.
    Trả về dict: {ticker: {"primary": str, "secondary": list}}
    """
    meta_path = Path(warehouse_root) / "_meta" / "industry_classification.parquet"
    if not meta_path.exists():
        return {}
    try:
        import pyarrow.parquet as pq
        import json as _json
        df = pq.read_table(str(meta_path),
                           columns=["ticker", "primary_industry",
                                    "secondary_industries"]).to_pandas()
        result = {}
        for _, row in df.iterrows():
            sec = []
            try:
                sec = _json.loads(row.get("secondary_industries") or "[]")
            except Exception:
                pass
            result[str(row["ticker"])] = {
                "primary":   str(row["primary_industry"]),
                "secondary": sec,
            }
        console.log(f"[green]🏭 Industry map loaded:[/green] {len(result):,} tickers")
        return result
    except Exception as e:
        console.log(f"[yellow]⚠ Industry map load failed: {e}[/yellow]")
        return {}


# ═════════════════════════════════════════════════════════════════════════════
# Kho đứng im — mã trễ quá N phiên không xét preset (EOD lẫn Live Scan)
# ═════════════════════════════════════════════════════════════════════════════

# Đo 17/10 trên kho thật (1.723 mã): trễ 1–5 phiên phần lớn là mã ít thanh khoản (không khớp
# lệnh thì không có bar; mật độ bar trung vị 0,40–0,53), từ 6 phiên mật độ còn ≤ 0,23 và 385 mã
# trễ > 20 phiên (cách ly basis drift, ngừng giao dịch, huỷ niêm yết).
STALE_SESSIONS = 5           # env VNSTOCK_SCREENER_STALE_SESSIONS (0 = tắt lọc)


def stale_limit() -> int:
    raw = (os.environ.get("VNSTOCK_SCREENER_STALE_SESSIONS") or "").strip()
    try:
        return int(raw) if raw else STALE_SESSIONS
    except ValueError:
        return STALE_SESSIONS


def stale_sessions(last_bar, sessions) -> int:
    """Số phiên của lịch `sessions` SAU ngày của `last_bar` — đếm phiên chứ không đếm ngày lịch
    (cuối tuần, ngày lễ không nằm trong lịch). Lịch rỗng ⇒ 0."""
    s = pd.DatetimeIndex(sessions).normalize().unique().sort_values()
    return int(len(s) - s.searchsorted(pd.Timestamp(last_bar).normalize(), side="right"))


def stale_lag(last_bar, sessions) -> int:
    """Số phiên trễ của `last_bar` khi VƯỢT `stale_limit()` (≤ 0 = tắt lọc), không thì 0."""
    limit = stale_limit()
    lag = stale_sessions(last_bar, sessions) if limit > 0 else 0
    return lag if lag > limit else 0


def market_sessions(prices_dir, years: int = 2) -> pd.DatetimeIndex:
    """Lịch phiên = ngày có bar VNINDEX trong kho (`years` thư mục năm mới nhất); chưa có ⇒ rỗng
    (không lọc). VNINDEX chậm k phiên thì mã bị đếm thiếu k phiên: lọc lỏng đi, không loại oan."""
    import pyarrow.parquet as pq
    files = [pf for yd in sorted((Path(prices_dir) / "ticker=VNINDEX").glob("year=*"))[-years:]
             for pf in yd.glob("*.parquet")]
    times = [pq.read_table(str(pf), columns=["time"]).column(0).to_pandas() for pf in files]
    return pd.DatetimeIndex(pd.to_datetime(pd.concat(times)) if times else [])


# ═════════════════════════════════════════════════════════════════════════════
# Indicator engine — pure pandas, no extra deps
# ═════════════════════════════════════════════════════════════════════════════

def _calc_indicators(df: pd.DataFrame) -> dict:
    """
    Tính RSI, MACD, EMA, BB, Volume spike cho một ticker.
    Input: DataFrame với cột time, open, high, low, close, volume
    Output: dict với các chỉ số mới nhất
    """
    if df is None or len(df) < 30:
        return {}

    c = df["close"].astype(float)
    v = df["volume"].astype(float)

    result = {
        "last_close":  round(float(c.iloc[-1]), 2),
        "last_volume": int(v.iloc[-1]),
    }

    # ── Thay đổi giá ──────────────────────────────────────────────────────────
    if len(c) >= 2:
        result["chg_1d_pct"] = round((c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)
    if len(c) >= 6:
        result["chg_5d_pct"] = round((c.iloc[-1] / c.iloc[-6] - 1) * 100, 2)
    if len(c) >= 21:
        result["chg_20d_pct"] = round((c.iloc[-1] / c.iloc[-21] - 1) * 100, 2)

    # ── RSI 14 ────────────────────────────────────────────────────────────────
    if len(c) >= 15:
        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = (100 - (100 / (1 + rs))).iloc[-1]
        result["rsi_14"] = round(float(rsi), 1) if not np.isnan(rsi) else None

    # ── EMA ───────────────────────────────────────────────────────────────────
    for span in (9, 21, 50, 200):
        if len(c) >= span:
            ema = float(c.ewm(span=span, adjust=False).mean().iloc[-1])
            result[f"ema_{span}"] = round(ema, 2)

    # ── MACD 12-26-9 ──────────────────────────────────────────────────────────
    if len(c) >= 27:
        ema12  = c.ewm(span=12, adjust=False).mean()
        ema26  = c.ewm(span=26, adjust=False).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist   = macd - signal
        result["macd_hist"]   = round(float(hist.iloc[-1]), 4)
        result["macd_signal_val"] = round(float(signal.iloc[-1]), 4)
        # Crossover: histogram đổi dấu
        if len(hist) >= 2:
            result["macd_cross"] = (
                "BUY"  if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0 else
                "SELL" if hist.iloc[-1] < 0 and hist.iloc[-2] >= 0 else
                "BULL" if hist.iloc[-1] > 0 else "BEAR"
            )

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    if len(c) >= 20:
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        bb_up = (sma20 + 2 * std20).iloc[-1]
        bb_lo = (sma20 - 2 * std20).iloc[-1]
        price = c.iloc[-1]
        if not (np.isnan(bb_up) or np.isnan(bb_lo)) and (bb_up - bb_lo) > 0:
            result["bb_pct"] = round((price - bb_lo) / (bb_up - bb_lo) * 100, 1)

    # ── Volume spike (so với MA20 volume) ─────────────────────────────────────
    if len(v) >= 20:
        vol_ma20 = v.rolling(20).mean().iloc[-1]
        if vol_ma20 > 0:
            result["vol_spike"] = round(float(v.iloc[-1] / vol_ma20), 2)

    # ── Trend signals ─────────────────────────────────────────────────────────
    e9  = result.get("ema_9")
    e21 = result.get("ema_21")
    e50 = result.get("ema_50")
    e200= result.get("ema_200")
    p   = result["last_close"]

    if e9 and e21:
        result["ema_trend"] = "UP" if e9 > e21 else "DOWN"
    if e50 and e200:
        result["long_trend"] = "BULL" if e50 > e200 else "BEAR"
    if e200:
        result["above_ma200"] = p > e200

    # ── 52-week high/low ──────────────────────────────────────────────────────
    year_df = df.tail(252)
    if len(year_df) >= 50:
        result["52w_high"] = round(float(year_df["high"].max()), 2)
        result["52w_low"]  = round(float(year_df["low"].min()), 2)
        result["52w_pct"]  = round(
            (p - result["52w_low"]) /
            (result["52w_high"] - result["52w_low"]) * 100, 1
        ) if result["52w_high"] != result["52w_low"] else 50.0

    # ── Mẫu nến + ConnorsRSI (khảo sát StockSharp 2026-07-15) — best-effort ──
    try:
        from vnstock_candle_patterns import detect_df as _detect_patterns
        hits = _detect_patterns(df)
        if hits:
            result["candle_patterns"] = ",".join(h["key"] for h in hits[:4])
            result["candle_bull"] = any(h["direction"] == "bull" for h in hits)
            result["candle_bear"] = any(h["direction"] == "bear" for h in hits)
    except Exception:
        pass
    try:
        from vnstock_indicators import connors_rsi as _connors_rsi
        crsi = _connors_rsi(c.values)
        if crsi is not None:
            result["crsi"] = round(float(crsi), 1)
    except Exception:
        pass

    # ── Double bottom W + Heikin-Ashi streak (khảo sát quant-trading) ────────
    try:
        from vnstock_indicators import double_bottom_w as _dbw
        db = _dbw(c.values, low=df["low"].astype(float).values)
        if db:
            result["double_bottom"] = True
            result["db_neckline"] = db["neckline"]
    except Exception:
        pass
    try:
        from vnstock_indicators import ha_trend_streak as _ha_streak
        streak = _ha_streak(df["open"].astype(float).values,
                            df["high"].astype(float).values,
                            df["low"].astype(float).values, c.values)
        if streak:
            result["ha_streak"] = int(streak)
    except Exception:
        pass

    return result


# ═════════════════════════════════════════════════════════════════════════════
# Screener Presets
# ═════════════════════════════════════════════════════════════════════════════

PRESETS = {
    "oversold": {
        "desc": "RSI < 30 — Cổ phiếu quá bán, tiềm năng hồi phục",
        "filter": lambda r: r.get("rsi_14", 999) < 30,
        "sort_by": "rsi_14",
        "sort_asc": True,
    },
    "overbought": {
        "desc": "RSI > 70 — Cổ phiếu quá mua, cảnh báo điều chỉnh",
        "filter": lambda r: r.get("rsi_14", 0) > 70,
        "sort_by": "rsi_14",
        "sort_asc": False,
    },
    "momentum": {
        "desc": "MACD Bullish + EMA uptrend — Đà tăng mạnh",
        "filter": lambda r: (
            r.get("macd_cross") in ("BUY", "BULL") and
            r.get("ema_trend") == "UP"
        ),
        "sort_by": "chg_20d_pct",
        "sort_asc": False,
    },
    "breakout": {
        "desc": "Gần 52-week high + Volume spike — Breakout tiềm năng",
        "filter": lambda r: (
            r.get("52w_pct", 0) > 85 and
            r.get("vol_spike", 0) > 1.5
        ),
        "sort_by": "vol_spike",
        "sort_asc": False,
    },
    "reversal": {
        "desc": "Gần 52-week low + RSI < 40 — Đáy tiềm năng",
        "filter": lambda r: (
            r.get("52w_pct", 100) < 15 and
            r.get("rsi_14", 100) < 40
        ),
        "sort_by": "52w_pct",
        "sort_asc": True,
    },
    "golden_cross": {
        "desc": "EMA9 > EMA21 + EMA50 > EMA200 — Golden cross",
        "filter": lambda r: (
            r.get("ema_trend") == "UP" and
            r.get("long_trend") == "BULL" and
            r.get("above_ma200", False)
        ),
        "sort_by": "chg_20d_pct",
        "sort_asc": False,
    },
    "volume_surge": {
        "desc": "Volume > 3x MA20 — Dòng tiền đột biến",
        "filter": lambda r: r.get("vol_spike", 0) > 3.0,
        "sort_by": "vol_spike",
        "sort_asc": False,
    },
    "strong_uptrend": {
        "desc": "Tăng > 5% trong 20 ngày + MACD bull + trên MA200",
        "filter": lambda r: (
            r.get("chg_20d_pct", 0) > 5 and
            r.get("macd_cross") in ("BUY", "BULL") and
            r.get("above_ma200", False)
        ),
        "sort_by": "chg_20d_pct",
        "sort_asc": False,
    },
    "value": {
        "desc": "P/E thấp hơn median ngành + ROE cao hơn median ngành — Cổ phiếu giá trị",
        "filter": None,  # Filter động trong scan()
        "sort_by": "pe_vs_industry",
        "sort_asc": True,
    },
    # ── 3 preset mới từ khảo sát StockSharp (2026-07-15) — được chấm alpha
    # tự động qua vnstock_preset_score như mọi preset khác ─────────────────
    "candle_bull": {
        "desc": "Mẫu nến đảo chiều tăng (Hammer/Engulfing/Morning Star…) — tín hiệu nến, cần xác nhận",
        "filter": lambda r: bool(r.get("candle_bull")),
        "sort_by": "vol_spike",
        "sort_asc": False,
    },
    "candle_bear": {
        "desc": "Mẫu nến đảo chiều giảm (Shooting Star/Bearish Engulfing/Evening Star…) — cảnh báo chốt lời",
        "filter": lambda r: bool(r.get("candle_bear")),
        "sort_by": "vol_spike",
        "sort_asc": False,
    },
    "crsi_oversold": {
        "desc": "ConnorsRSI < 10 — quá bán ngắn hạn (mean-reversion nâng cao)",
        "filter": lambda r: (r.get("crsi") is not None and r["crsi"] < 10),
        "sort_by": "crsi",
        "sort_asc": True,
    },
    # ── 2 preset từ khảo sát je-suis-tm/quant-trading (2026-07-15) ────────
    "double_bottom": {
        "desc": "Hai đáy hình W neo Bollinger + vừa vượt neckline — đảo chiều cấu trúc",
        "filter": lambda r: bool(r.get("double_bottom")),
        "sort_by": "vol_spike",
        "sort_asc": False,
    },
    "ha_trend": {
        "desc": "≥3 nến Heikin-Ashi xanh sạch liên tiếp (không râu dưới) — trend tăng sạch",
        "filter": lambda r: (r.get("ha_streak") or 0) >= 3,
        "sort_by": "ha_streak",
        "sort_asc": False,
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# Main Screener
# ═════════════════════════════════════════════════════════════════════════════

class MarketScreener:
    """
    Screener toàn thị trường từ local Parquet warehouse.
    Không cần gọi API — đọc từ disk, tính indicator, lọc.
    """

    sessions = pd.DatetimeIndex([])     # lịch phiên VNINDEX; rỗng = không lọc mã kho cũ

    def __init__(self, warehouse_root: str = "data_warehouse", lookback_days: int = 300):
        self.prices_dir   = Path(warehouse_root) / "prices"
        self.lookback_days = lookback_days

        if not self.prices_dir.exists():
            console.print(f"[red]❌ Warehouse not found: {self.prices_dir}[/red]")
            raise FileNotFoundError(f"{self.prices_dir} not found")

        # Lấy danh sách tickers có trong warehouse — lọc CW/Futures/Bond
        import re as _re2
        _CW  = _re2.compile(r"^C[A-Z]{2,4}\d{4}$")
        _OLD = _re2.compile(r"^[A-Z]{2,4}\d{5,6}$")
        _FUT = _re2.compile(r"^[A-Z]{2,6}F\d{4}$")
        _FT2 = _re2.compile(r"^[A-Z]{2}\d{2}F\d{4}$")
        def _ok(s):
            s = s.upper()
            if not s or s[0].isdigit(): return False
            return not (_CW.match(s) or _OLD.match(s) or _FUT.match(s) or _FT2.match(s))

        all_tickers = [
            p.name.replace("ticker=", "")
            for p in self.prices_dir.iterdir()
            if p.is_dir() and p.name.startswith("ticker=")
        ]
        self.tickers = sorted([t for t in all_tickers if _ok(t)])
        console.log(
            f"[green]📦 Warehouse loaded:[/green] {len(self.tickers)} stocks "
            f"[dim](filtered from {len(all_tickers)} total)[/dim]"
        )

        # Load industry classification (optional — nếu có)
        self.industry_map = _load_industry_map(warehouse_root)

        # Load fundamentals (optional — nếu đã chạy fundamental_updater)
        self.fundamentals = _load_fundamentals(warehouse_root)
        self.industry_medians = _calc_industry_medians(
            self.fundamentals, warehouse_root
        ) if self.fundamentals is not None else {}

        # ── Bộ nhớ chỉ báo dùng chung cho MỌI preset ─────────────────────
        # `run_all_presets` lặp preset ở NGOÀI, `scan()` lặp mã ở TRONG, và
        # filter của preset chỉ được áp SAU khi đã đọc parquet + tính trọn bộ
        # chỉ báo. 14 preset ⇒ **14 lượt quét kho y hệt nhau** cho cùng ~1.600
        # mã. Đo 25/08 trên máy thật: bước `screener` 1.318s = 22 phút, nặng
        # nhất cả phát — hơn cả `sync`.
        #
        # `_calc_indicators(df)` là hàm THUẦN của df, và df là hàm thuần của
        # (ticker, lookback_days). Không có gì phụ thuộc preset. Nên nhớ kết
        # quả một lần là đủ: 14 lượt → 1.
        #
        # Cache sống trên MỘT instance, trong tiến trình ngắn của
        # `vnstock_runner.py`, và không bước nào ghi vào `prices/` lúc đó ⇒
        # không thể ôi.
        self._ind_cache: "dict[str, tuple[int, dict] | None]" = {}

        # Mã → số phiên trễ: kho đứng im (`stale_lag`) ⇒ không xét preset nào; kho giữ nguyên.
        self.stale: "dict[str, int]" = {}
        try:
            self.sessions = market_sessions(self.prices_dir)
        except Exception as e:
            console.log(f"[yellow]⚠ Lịch phiên VNINDEX lỗi ({e}) — không lọc mã kho cũ[/yellow]")
        else:
            if not len(self.sessions):
                console.log("[yellow]⚠ Kho chưa có VNINDEX — không lọc mã kho cũ[/yellow]")

    def _indicators_for(self, ticker: str, min_rows: int) -> "dict | None":
        """Chỉ báo của một mã — đọc parquet + tính TỐI ĐA MỘT LẦN mỗi lượt chạy.

        Trả bản SAO: chỗ gọi có gắn thêm `ticker`/`industry` vào dict, sửa
        thẳng vào cache là preset sau nhận rác của preset trước.
        """
        if ticker not in self._ind_cache:
            df = self._load_ticker(ticker)
            if df.empty:
                self._ind_cache[ticker] = None
            elif len(self.sessions) and (lag := stale_lag(df["time"].iloc[-1], self.sessions)):
                self.stale[ticker] = lag
                self._ind_cache[ticker] = None
            else:
                ind = _calc_indicators(df)
                self._ind_cache[ticker] = (len(df), ind) if ind else None
        entry = self._ind_cache[ticker]
        if entry is None:
            return None
        n_rows, ind = entry
        # `min_rows` đổi theo preset nên PHẢI xét lại mỗi lượt, không được
        # nướng vào cache.
        if n_rows < min_rows:
            return None
        return dict(ind)

    def _load_ticker(self, ticker: str) -> pd.DataFrame:
        """Load dữ liệu gần nhất cho một ticker."""
        ticker_dir = self.prices_dir / f"ticker={ticker}"
        if not ticker_dir.exists():
            return pd.DataFrame()
        try:
            # Chỉ load năm gần nhất để nhanh hơn
            cutoff_year = datetime.now().year - (self.lookback_days // 365 + 1)
            year_dirs = [
                d for d in ticker_dir.iterdir()
                if d.is_dir() and d.name.startswith("year=")
                and int(d.name.replace("year=", "")) >= cutoff_year
            ]
            if not year_dirs:
                return pd.DataFrame()

            frames = []
            for yd in sorted(year_dirs):
                for pf in yd.glob("*.parquet"):
                    import pyarrow.parquet as pq
                    tbl = pq.read_table(str(pf),
                                        columns=["time","open","high","low","close","volume"])
                    frames.append(tbl.to_pandas())
                    del tbl

            if not frames:
                return pd.DataFrame()

            df = pd.concat(frames, ignore_index=True)
            df["time"] = pd.to_datetime(df["time"])
            df = df.sort_values("time").tail(self.lookback_days).reset_index(drop=True)
            from vnstock_price_units import normalize_price_units
            return normalize_price_units(df)
        except Exception:
            return pd.DataFrame()

    def scan(
        self,
        preset: str = None,
        custom_filter=None,
        tickers: list = None,
        min_rows: int = 60,
        industry: str = None,
        include_secondary: bool = False,
    ) -> pd.DataFrame:
        """
        Scan toàn thị trường và trả về DataFrame kết quả.

        Args:
            preset            : Tên preset ('oversold', 'momentum', ...)
            custom_filter     : Hàm filter tùy chỉnh: lambda row_dict -> bool
            tickers           : Giới hạn danh sách tickers (None = tất cả)
            min_rows          : Bỏ qua ticker có ít hơn N rows
            industry          : Lọc theo ngành (VD: 'Ngân hàng', 'Bất động sản')
            include_secondary : Tính cả ngành phụ khi lọc (default: False)

        Returns:
            DataFrame đã được lọc và sắp xếp
        """
        # Lọc tickers theo ngành nếu có industry_map
        if industry and self.industry_map:
            industry_tickers = [
                t for t, info in self.industry_map.items()
                if info["primary"] == industry or
                   (include_secondary and industry in info["secondary"])
            ]
            if not industry_tickers:
                console.print(f"[yellow]⚠ Không tìm thấy mã nào trong ngành '{industry}'[/yellow]")
                # Gợi ý ngành gần nhất
                all_industries = sorted(set(v["primary"] for v in self.industry_map.values()))
                matches = [g for g in all_industries if industry.lower() in g.lower()]
                if matches:
                    console.print(f"  Ngành gần nhất: {', '.join(matches[:3])}")
                return pd.DataFrame()
            # Intersect với tickers có giá
            scan_list = [t for t in (tickers or self.tickers) if t in set(industry_tickers)]
            console.log(
                f"  [cyan]🏭 Lọc ngành '{industry}':[/cyan] "
                f"{len(industry_tickers)} mã có phân loại → "
                f"{len(scan_list)} mã có dữ liệu giá"
            )
        else:
            scan_list = tickers or self.tickers

        preset_cfg = PRESETS.get(preset) if preset else None
        filter_fn  = custom_filter or (preset_cfg["filter"] if preset_cfg else None)

        industry_tag = f" [{industry}]" if industry else ""
        if preset_cfg:
            console.rule(f"[bold cyan]🔍 Screener: {preset.upper()}{industry_tag}[/bold cyan]")
            console.print(f"  [dim]{preset_cfg['desc']}[/dim]\n")
        else:
            console.rule(f"[bold cyan]🔍 Market Scan{industry_tag}[/bold cyan]")

        results = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(),
            TaskProgressColumn(), TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning...", total=len(scan_list))

            for ticker in scan_list:
                progress.update(task, description=f"[cyan]{ticker:6s}[/cyan]", advance=1)

                ind = self._indicators_for(ticker, min_rows)
                if not ind:
                    continue

                ind["ticker"] = ticker

                # Thêm thông tin ngành nếu có
                if self.industry_map and ticker in self.industry_map:
                    info = self.industry_map[ticker]
                    ind["industry"] = info["primary"]
                    ind["industry_secondary"] = ", ".join(info["secondary"]) if info["secondary"] else ""

                # Áp filter
                if filter_fn:
                    try:
                        if not filter_fn(ind):
                            continue
                    except Exception:
                        continue

                # Preset value: filter dynamic theo fundamental + ngành
                if preset == "value":
                    import math
                    fund_row = (
                        self.fundamentals.loc[ticker].to_dict()
                        if self.fundamentals is not None and ticker in self.fundamentals.index
                        else {}
                    )
                    industry = self.industry_map.get(ticker, {}).get("primary", "Khác")
                    med = self.industry_medians.get(industry, {})

                    pe      = fund_row.get("pe")
                    roe     = fund_row.get("roe")
                    med_pe  = med.get("pe",  float("nan"))
                    med_roe = med.get("roe", float("nan"))

                    def _bad(v):
                        return v is None or (isinstance(v, float) and math.isnan(v))

                    if _bad(pe) or _bad(roe) or _bad(med_pe) or _bad(med_roe):
                        continue
                    if float(pe) <= 0 or float(pe) >= float(med_pe):
                        continue
                    if float(roe) <= float(med_roe):
                        continue

                    ind["pe"]               = round(float(pe), 2)
                    ind["roe"]              = round(float(roe), 2)
                    ind["industry"]         = industry
                    ind["industry_med_pe"]  = round(float(med_pe), 2)
                    ind["industry_med_roe"] = round(float(med_roe), 2)
                    ind["pe_vs_industry"]   = round(float(pe) / float(med_pe), 3)
                    ind["roe_vs_industry"]  = round(float(roe) / float(med_roe), 3)

                results.append(ind)

        if not results:
            console.print("[yellow]⚠ Không có kết quả phù hợp[/yellow]")
            return pd.DataFrame()

        result_df = pd.DataFrame(results)

        # Sắp xếp
        sort_col = preset_cfg["sort_by"] if preset_cfg else "chg_1d_pct"
        sort_asc = preset_cfg.get("sort_asc", False) if preset_cfg else False
        if sort_col in result_df.columns:
            result_df = result_df.sort_values(sort_col, ascending=sort_asc)

        return result_df.reset_index(drop=True)

    def print_results(self, df: pd.DataFrame, top: int = 20):
        """Hiển thị kết quả dạng rich table."""
        if df.empty:
            return

        display_df = df.head(top)
        total = len(df)

        t = Table(
            title=f"📊 Kết quả Screener — Top {min(top, total)}/{total} cổ phiếu",
            box=box.SIMPLE_HEAVY, show_lines=False
        )

        # Hiển thị cột Ngành nếu có dữ liệu
        show_industry = "industry" in display_df.columns

        cols = [
            ("Ticker",    "ticker",      "cyan",   8),
            ("Giá",       "last_close",  "white",  10),
            ("1D%",       "chg_1d_pct",  "white",  8),
            ("5D%",       "chg_5d_pct",  "white",  8),
            ("20D%",      "chg_20d_pct", "white",  8),
            ("RSI",       "rsi_14",      "white",  7),
            ("MACD",      "macd_cross",  "white",  7),
            ("Trend",     "ema_trend",   "white",  7),
            ("Vol×",      "vol_spike",   "white",  7),
            ("BB%",       "bb_pct",      "white",  7),
            ("52W%",      "52w_pct",     "white",  7),
        ]
        if show_industry:
            cols.append(("Ngành", "industry", "dim", 22))

        for header, _, style, width in cols:
            t.add_column(header, style=style, width=width, justify="right")

        for _, row in display_df.iterrows():
            def _fmt(col, decimals=1, suffix=""):
                v = row.get(col)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return "[dim]-[/dim]"
                return f"{v:.{decimals}f}{suffix}"

            def _pct_color(col):
                v = row.get(col)
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    return "[dim]-[/dim]"
                color = "green" if v > 0 else ("red" if v < 0 else "white")
                return f"[{color}]{v:+.1f}%[/{color}]"

            def _rsi_color():
                v = row.get("rsi_14")
                if v is None: return "[dim]-[/dim]"
                color = "green" if v < 35 else ("red" if v > 65 else "white")
                return f"[{color}]{v:.0f}[/{color}]"

            def _macd_color():
                v = row.get("macd_cross", "-")
                if v in ("BUY",):  return "[bold green]BUY[/bold green]"
                if v == "BULL":    return "[green]BULL[/green]"
                if v in ("SELL",): return "[bold red]SELL[/bold red]"
                if v == "BEAR":    return "[red]BEAR[/red]"
                return "[dim]-[/dim]"

            def _trend_color():
                v = row.get("ema_trend", "-")
                return "[green]UP[/green]" if v == "UP" else "[red]DN[/red]"

            t.add_row(
                str(row.get("ticker", "")),
                _fmt("last_close", 1),
                _pct_color("chg_1d_pct"),
                _pct_color("chg_5d_pct"),
                _pct_color("chg_20d_pct"),
                _rsi_color(),
                _macd_color(),
                _trend_color(),
                _fmt("vol_spike", 1, "x"),
                _fmt("bb_pct", 0, "%"),
                _fmt("52w_pct", 0, "%"),
            )

        console.print(t)
        console.print(
            f"  [dim]Scanned {len(self.tickers):,} tickers  |  "
            f"Matched: {total}  |  "
            f"Shown: {min(top, total)}[/dim]"
        )


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VnStock Market Screener")
    parser.add_argument("--preset",    default="oversold",
                        choices=list(PRESETS.keys()),
                        help="Preset lọc cổ phiếu")
    parser.add_argument("--top",       type=int, default=20,
                        help="Hiện top N kết quả")
    parser.add_argument("--export",    action="store_true",
                        help="Xuất kết quả CSV")
    parser.add_argument("--warehouse", default="data_warehouse",
                        help="Đường dẫn warehouse")
    parser.add_argument("--lookback",  type=int, default=300,
                        help="Số ngày dữ liệu để tính indicator")
    parser.add_argument("--industry",   default=None,
                        help="Lọc theo ngành (VD: 'Ngân hàng', 'Bất động sản')")
    parser.add_argument("--list-industries", action="store_true",
                        help="Liệt kê tất cả ngành có trong warehouse")
    parser.add_argument("--include-secondary", action="store_true",
                        help="Tính cả ngành phụ khi lọc --industry")
    parser.add_argument("--list-presets", action="store_true",
                        help="Liệt kê tất cả presets")
    args = parser.parse_args()

    if args.list_presets:
        console.rule("[bold]📋 Danh sách Presets[/bold]")
        t = Table(box=box.SIMPLE_HEAVY)
        t.add_column("Preset", style="cyan")
        t.add_column("Mô tả")
        for name, cfg in PRESETS.items():
            t.add_row(name, cfg["desc"])
        console.print(t)
        exit(0)

    screener = MarketScreener(
        warehouse_root=args.warehouse,
        lookback_days=args.lookback,
    )

    if args.list_industries:
        if screener.industry_map:
            from collections import Counter
            counts = Counter(v["primary"] for v in screener.industry_map.values())
            console.rule("[bold]🏭 Danh sách Ngành[/bold]")
            t = Table(box=box.SIMPLE_HEAVY)
            t.add_column("Ngành", style="cyan")
            t.add_column("Số mã", justify="right", style="bold")
            for industry, count in sorted(counts.items(), key=lambda x: -x[1]):
                t.add_row(industry, str(count))
            console.print(t)
        else:
            console.print("[yellow]⚠ Chưa có dữ liệu phân loại ngành — chạy vnstock_classifier.py trước[/yellow]")
        exit(0)

    result_df = screener.scan(
        preset=args.preset,
        industry=args.industry,
        include_secondary=args.include_secondary,
    )
    screener.print_results(result_df, top=args.top)

    if args.export and not result_df.empty:
        fname = f"screen_{args.preset}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        result_df.to_csv(fname, index=False, encoding="utf-8-sig")
        console.print(f"[green]✅ Saved → {fname}[/green]")
