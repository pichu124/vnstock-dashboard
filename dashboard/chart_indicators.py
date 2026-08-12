"""Chỉ báo kỹ thuật cho chart 4 panel — pandas thuần, không dính Streamlit.

Tách khỏi `vnstock_dashboard.py` (12/08). Bản replica cũ trong
`tests/test_dashboard.py` ĐÃ TRÔI: nó giữ công thức RSI cũ
(`100 - 100/(1+gain/loss.replace(0, nan))`) nên để NaN ở đuôi chuỗi, trong khi
đồ thật đã vá thành `.where(loss != 0, 100.0)`. Test xanh trên bản chép tay
suốt thời gian đó = không bảo vệ được gì.

⚠️ Bất biến (docs/CLAUDE-NOTES.md): 4 panel Price/Volume/RSI/MACD phải CÙNG SỐ
BAR. Vì thế RSI không được để NaN ở CUỐI chuỗi — panel sẽ auto-fit ngắn hơn
panel nến, và chart lệch trục. Bar warmup emit whitespace, không được skip.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RSI_PERIOD = 14
BB_PERIOD = 20
VOL_MA_PERIOD = 20
EMA_SPANS = (9, 21, 50, 200)

# Khoảng cách giữa 2 bar cuối < 2 giờ ⇒ dữ liệu intraday (bar phút), không
# phải daily. Chỉ khi đó VWAP mới có ý nghĩa.
_INTRADAY_GAP_SECONDS = 7200
_INTRADAY_MIN_BARS = 50


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Thêm cột chỉ báo vào df giá. Trả DataFrame MỚI, giữ nguyên số dòng."""
    df = df.copy()
    c = df["close"].astype(float)

    # RSI 14 — khi loss = 0 (chuỗi toàn tăng) ép RSI=100 thay vì NaN.
    # `loss.replace(0, NaN)` ngây thơ để lại lỗ hổng ở CUỐI chuỗi, khiến panel
    # RSI auto-fit ngắn hơn panel nến.
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    df["rsi"] = rsi.where(loss != 0, 100.0)

    # EMA — chỉ tính khi đủ data (tránh EMA chưa hội tụ trên chuỗi ngắn)
    for span in EMA_SPANS:
        if len(c) >= span:
            df[f"ema{span}"] = c.ewm(span=span, adjust=False).mean()
        else:
            df[f"ema{span}"] = np.nan

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Bollinger Bands 20
    sma20 = c.rolling(BB_PERIOD).mean()
    std20 = c.rolling(BB_PERIOD).std()
    df["bb_up"] = sma20 + 2 * std20
    df["bb_lo"] = sma20 - 2 * std20
    df["bb_mid"] = sma20

    # Volume MA20
    df["vol_ma20"] = df["volume"].astype(float).rolling(VOL_MA_PERIOD).mean()

    # VWAP — chỉ có ý nghĩa cho intraday, và PHẢI reset mỗi phiên
    # (cumulative trong ngày, không cộng dồn qua ngày).
    if _is_intraday(df):
        tp = (df["high"].astype(float) + df["low"].astype(float) + c) / 3
        vol = df["volume"].astype(float).replace(0, np.nan)

        dates = df["time"].dt.date
        cum_tp_vol = (tp * vol).groupby(dates).cumsum()
        cum_vol = vol.groupby(dates).cumsum()
        df["vwap"] = cum_tp_vol / cum_vol

        # VWAP bands ±1σ, ±2σ (cũng reset mỗi ngày)
        vwap_dev = (((tp - df["vwap"]) ** 2) * vol).groupby(dates).cumsum() / cum_vol
        vwap_std = np.sqrt(vwap_dev)
        df["vwap_upper1"] = df["vwap"] + vwap_std
        df["vwap_lower1"] = df["vwap"] - vwap_std
        df["vwap_upper2"] = df["vwap"] + 2 * vwap_std
        df["vwap_lower2"] = df["vwap"] - 2 * vwap_std

    return df


def _is_intraday(df: pd.DataFrame) -> bool:
    """Bar phút hay bar ngày? Đo bằng khoảng cách 2 bar cuối."""
    if len(df) <= _INTRADAY_MIN_BARS:
        return False
    gap = (df["time"].iloc[-1] - df["time"].iloc[-2]).total_seconds()
    return gap < _INTRADAY_GAP_SECONDS
