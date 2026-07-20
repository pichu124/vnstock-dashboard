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
import logging
import os
import re
import subprocess
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

# Load .env file if present (API keys for AI Brief agents, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass

log = logging.getLogger("vnstock_dashboard")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

from vnstock_auth import ensure_api_key, get_api_key

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
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
        get_all_listed_symbols,
        is_futures,
    )
    WSS_AVAILABLE = True
except Exception:
    WSS_AVAILABLE = False
    VN30_SYMBOLS, INDEX_SYMBOLS, FUTURES_SYMBOLS = [], [], []
    def is_futures(ticker):  # type: ignore
        return False
    def get_all_listed_symbols():  # type: ignore
        return []

# Safety net: ensure these names always exist even if the try/except above
# was interrupted by a non-standard exception path.
if "FUTURES_SYMBOLS" not in dir():
    FUTURES_SYMBOLS = []  # type: ignore
if "VN30_SYMBOLS" not in dir():
    VN30_SYMBOLS = []  # type: ignore
if "INDEX_SYMBOLS" not in dir():
    INDEX_SYMBOLS = []  # type: ignore

# Re-apply Golden key AFTER all vnstock imports (they can auto-register free keys)
ensure_api_key()

# ── Stock filter (loại warrant, CW, bond — giữ lại stock thật) ────────────
_CW_VN  = re.compile(r"^C[A-Z]{2,4}\d{4}$")     # Covered warrants: CVIC2513
_CW_OLD = re.compile(r"^[A-Z]{2,4}\d{5,6}$")     # Old format bonds: VBA121033

def _is_stock(s: str) -> bool:
    """Return True nếu ticker là cổ phiếu (không phải warrant/CW/bond/futures)."""
    s = s.upper().strip()
    if not s or s[0].isdigit():
        return False
    return not (_CW_VN.match(s) or _CW_OLD.match(s) or is_futures(s))

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
SESSION_STATS_PATH = Path("data_warehouse/_meta/market_session_stats.json")


# ── Sector groups (31 → 15 nhóm) ────────────────────────────────────────────
SECTOR_GROUPS = {
    "Ngân hàng":            "Ngân hàng",
    "Chứng khoán & Đầu tư tài chính": "Chứng khoán",
    "Bảo hiểm":            "Bảo hiểm",
    "Bất động sản":         "Bất động sản",
    "Xây dựng & Hạ tầng":  "Xây dựng & Hạ tầng",
    "Thép & Kim loại":     "Thép & Kim loại",
    "Vật liệu xây dựng":  "Hoá chất & Vật liệu",
    "Hóa chất & Phân bón": "Hoá chất & Vật liệu",
    "Nhựa & Bao bì":      "Hoá chất & Vật liệu",
    "Cơ khí & Thiết bị công nghiệp": "Hoá chất & Vật liệu",
    "Dầu khí":             "Năng lượng",
    "Điện & Năng lượng tái tạo": "Năng lượng",
    "Khai khoáng & Tài nguyên":  "Năng lượng",
    "Công nghệ thông tin & Phần mềm": "Công nghệ",
    "Viễn thông":          "Công nghệ",
    "Truyền thông & Quảng cáo": "Công nghệ",
    "Bán lẻ & Thương mại": "Tiêu dùng",
    "Thực phẩm & Đồ uống": "Tiêu dùng",
    "Dệt may & May mặc":  "Tiêu dùng",
    "Thể thao & Hàng tiêu dùng": "Tiêu dùng",
    "Nông nghiệp & Thủy sản": "Nông & Thuỷ sản",
    "Y tế & Dược phẩm":   "Y tế & Dược",
    "Vận tải & Logistics": "Vận tải & Cảng",
    "Cảng & Hạ tầng logistics": "Vận tải & Cảng",
    "Du lịch & Khách sạn": "Dịch vụ & Du lịch",
    "Giáo dục":            "Dịch vụ & Du lịch",
    "Dịch vụ công ích & Môi trường": "Dịch vụ & Du lịch",
    "Dịch vụ tư vấn & Kiểm định": "Dịch vụ & Du lịch",
    "Đa ngành":            "Khác",
    "In ấn & Xuất bản":   "Khác",
    "Gỗ & Nội thất":      "Khác",
    "Khác":                "Khác",
}

SECTOR_ORDER = [
    "Ngân hàng", "Chứng khoán", "Bảo hiểm", "Bất động sản",
    "Xây dựng & Hạ tầng", "Thép & Kim loại", "Hoá chất & Vật liệu",
    "Năng lượng", "Công nghệ", "Tiêu dùng", "Nông & Thuỷ sản",
    "Y tế & Dược", "Vận tải & Cảng", "Dịch vụ & Du lịch", "Khác",
]

SECTOR_ICONS = {
    "Ngân hàng": "🏦", "Chứng khoán": "📈", "Bảo hiểm": "🛡",
    "Bất động sản": "🏠", "Xây dựng & Hạ tầng": "🏗", "Thép & Kim loại": "⚙️",
    "Hoá chất & Vật liệu": "🧪", "Năng lượng": "⚡", "Công nghệ": "💻",
    "Tiêu dùng": "🛒", "Nông & Thuỷ sản": "🌾", "Y tế & Dược": "💊",
    "Vận tải & Cảng": "🚢", "Dịch vụ & Du lịch": "✈️", "Khác": "📦",
}


def _get_sector(primary_industry: str) -> str:
    """Map ngành gốc → nhóm 15."""
    return SECTOR_GROUPS.get(primary_industry, "Khác")


@st.cache_data(ttl=600, show_spinner=False)
def _load_industry_map() -> dict:
    """Return {ticker: primary_industry} từ industry_classification.parquet. Cached 10 phút."""
    if not INDUSTRY_PATH.exists():
        return {}
    try:
        df = pq.read_table(
            str(INDUSTRY_PATH), columns=["ticker", "primary_industry"]
        ).to_pandas()
        return dict(zip(df["ticker"], df["primary_industry"]))
    except Exception:
        return {}


# ── Money Flow functions ─────────────────────────────────────────────────────

_NN_CACHE_PATH = Path("data_warehouse/_meta/nn_flow_cache.json")
_NN_CACHE_MAX_AGE = 600  # 10 phút — NN data không thay đổi liên tục

# Diagnostic info about foreign_buy/sell API calls (for NN Mua = 0 debugging).
# Uses module-level dict because function attributes don't survive Streamlit
# @st.cache_data wrappers.
_NN_DIAG: dict = {}


def _load_nn_from_disk() -> pd.DataFrame:
    """Load NN cache từ disk. Return empty DataFrame nếu cache quá cũ hoặc lỗi."""
    if not _NN_CACHE_PATH.exists():
        return pd.DataFrame()
    try:
        age = datetime.now().timestamp() - _NN_CACHE_PATH.stat().st_mtime
        if age > _NN_CACHE_MAX_AGE:
            return pd.DataFrame()  # stale
        data = json.loads(_NN_CACHE_PATH.read_text(encoding="utf-8"))
        df = pd.DataFrame(data)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            # Older caches may miss buy_value / sell_value — default to 0 so
            # downstream aggregations don't crash on KeyError.
            for col in ("buy_value", "sell_value"):
                if col not in df.columns:
                    df[col] = 0.0
        return df
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.warning("NN flow cache corrupt: %s", e)
        return pd.DataFrame()


def _save_nn_to_disk(df: pd.DataFrame):
    """Persist NN data to disk for fast reload."""
    try:
        _NN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        records = df.copy()
        records["date"] = records["date"].dt.strftime("%Y-%m-%d")
        _NN_CACHE_PATH.write_text(
            json.dumps(records.to_dict(orient="records"), ensure_ascii=False),
            encoding="utf-8",
        )
    except (OSError, ValueError):
        pass


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_foreign_net_flow(trading_days: int = 20, limit: int = 100) -> pd.DataFrame:
    """
    Fetch NN ròng per stock per day qua TopStock().foreign_buy/sell.

    Cache strategy (3 tầng):
      1. Disk: data_warehouse/_meta/nn_flow_cache.json (persist 10 phút)
         → load tức thì khi restart Streamlit hoặc refresh browser
      2. Streamlit: @st.cache_data(ttl=600) — 10 phút in-memory
         → load tức thì khi chuyển tab / đổi filter
      3. API: gọi TopStock mỗi 10 phút (~40 calls ≈ 20 giây)

    Return DataFrame [symbol, date, net_value (VND)].
    """
    # Tầng 1: thử disk cache trước
    cached = _load_nn_from_disk()
    if not cached.empty and len(cached) > 5:
        log.info("NN flow: loaded %d records from disk cache", len(cached))
        return cached

    # Tầng 3: fetch từ API
    from datetime import date as _d, timedelta as _td

    try:
        from vnstock_data import TopStock
    except ImportError:
        log.warning("vnstock_data not installed — NN flow unavailable")
        return pd.DataFrame(columns=["symbol", "date", "net_value"])

    ts = TopStock()
    all_rows = []
    errors = []
    today = _d.today()
    days_fetched = 0
    calendar_day = 0

    while days_fetched < trading_days and calendar_day < trading_days * 2:
        dt = today - _td(days=calendar_day)
        calendar_day += 1

        # Skip weekends
        if dt.weekday() >= 5:
            continue

        dt_str = dt.strftime("%Y-%m-%d")
        day_rows: dict[str, dict] = {}
        # Use explicit labels — `fetch_fn is ts.foreign_buy` doesn't work
        # because bound methods are created fresh on each attribute access,
        # so `fn_at_tuple_time is fn_at_compare_time` is always False.
        for _side, fetch_fn in (("buy", ts.foreign_buy), ("sell", ts.foreign_sell)):
            is_buy_endpoint = (_side == "buy")
            try:
                df = fetch_fn(date=dt_str, limit=limit)
                # Capture state on first attempt
                if days_fetched == 0 and f"{_side}_state" not in _NN_DIAG:
                    _NN_DIAG[f"{_side}_state"] = (
                        "empty" if (df is None or df.empty)
                        else f"ok ({len(df)} rows)"
                    )
                if df is not None and not df.empty:
                    if days_fetched == 0 and f"{_side}_cols" not in _NN_DIAG:
                        sample_row = dict(df.iloc[0]) if len(df) > 0 else {}
                        sample_row = {k: str(v)[:50] for k, v in sample_row.items()}
                        _NN_DIAG[f"{_side}_cols"] = list(df.columns)
                        _NN_DIAG[f"{_side}_sample"] = sample_row
                        _NN_DIAG[f"{_side}_rows"] = len(df)
                        log.info("TopStock %s cols: %s",
                                 f"foreign_{_side}", list(df.columns))
                    for _, row in df.iterrows():
                        sym = str(row.get("symbol", ""))
                        if not sym:
                            continue
                        # Extract the largest absolute numeric value from
                        # the row (excluding symbol/date columns). This is
                        # more robust than guessing column names, which vary
                        # across vnstock/vnstock_data versions.
                        val = 0.0
                        for k in ("buy_value", "sell_value", "net_value",
                                  "value", "total_value", "netvalue",
                                  "buyvalue", "sellvalue"):
                            v = row.get(k)
                            if v is not None:
                                try:
                                    fv = abs(float(v))
                                    if fv > val:
                                        val = fv
                                except (TypeError, ValueError):
                                    pass
                        # Fallback: pick largest numeric column value
                        if val == 0:
                            for k, v in row.items():
                                if k == "symbol" or "date" in str(k).lower():
                                    continue
                                try:
                                    fv = abs(float(v))
                                    if fv > val:
                                        val = fv
                                except (TypeError, ValueError):
                                    pass
                        entry = day_rows.setdefault(
                            sym, {"buy_value": 0.0, "sell_value": 0.0, "net_value": 0.0}
                        )
                        if is_buy_endpoint:
                            entry["buy_value"] = max(entry["buy_value"], val)
                        else:
                            entry["sell_value"] = max(entry["sell_value"], val)
            except Exception as e:
                if f"{_side}_state" not in _NN_DIAG:
                    _NN_DIAG[f"{_side}_state"] = f"exception: {type(e).__name__}: {str(e)[:150]}"
                errors.append(f"{fetch_fn.__name__}({dt_str}): {e}")
                continue

        for sym, ent in day_rows.items():
            # Always compute net from buy - sell (more reliable than
            # trusting the API's net_value which gets overwritten by
            # whichever endpoint runs last).
            ent["net_value"] = ent["buy_value"] - ent["sell_value"]
            all_rows.append({
                "symbol": sym,
                "date": dt_str,
                "buy_value": ent["buy_value"],
                "sell_value": ent["sell_value"],
                "net_value": ent["net_value"],
            })

        days_fetched += 1

    if errors:
        log.warning("NN flow fetch errors (%d): %s", len(errors), errors[:3])

    if not all_rows:
        log.warning("NN flow: 0 records fetched from API (days=%d)", trading_days)
        return pd.DataFrame(columns=["symbol", "date", "net_value"])

    result = pd.DataFrame(all_rows)
    result["date"] = pd.to_datetime(result["date"])
    for col in ("buy_value", "sell_value", "net_value"):
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0)
        else:
            result[col] = 0.0

    # Persist to disk for fast reload — chỉ save nếu có data thật
    if len(result) > 5:
        _save_nn_to_disk(result)
        log.info("NN flow: saved %d records to disk cache", len(result))
    return result


def _aggregate_nn_by_window(nn_df: pd.DataFrame, days: int) -> dict:
    """
    Aggregate net_value per symbol over time window.
    days=0 → most recent trading day only (1D view).
    days>0 → last N calendar days (5D, 20D views).
    Return {symbol: net_value_in_ty_VND}.
    """
    if nn_df.empty:
        return {}

    if days == 0:
        # 1D: lấy ngày giao dịch gần nhất trong dataset (không phải "hôm nay"
        # vì có thể hôm nay là cuối tuần, hoặc thị trường chưa mở)
        latest = pd.to_datetime(nn_df["date"]).max().normalize()
        filtered = nn_df[pd.to_datetime(nn_df["date"]) >= latest]
    else:
        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        filtered = nn_df[nn_df["date"] >= cutoff]

    if filtered.empty:
        return {}
    agg = filtered.groupby("symbol")["net_value"].sum()
    # VND → tỷ VND
    return {sym: round(val / 1e9, 1) for sym, val in agg.items()}


def _aggregate_nn_buy_sell_by_window(nn_df: pd.DataFrame, days: int) -> dict:
    """
    Aggregate NN buy_value and sell_value per symbol over the window.
    Returns {symbol: {"buy": tỷ_VND, "sell": tỷ_VND}}.
    Mirrors _aggregate_nn_by_window semantics for days=0 (latest-day-only).
    """
    if nn_df.empty or "buy_value" not in nn_df.columns:
        return {}
    if days == 0:
        latest = pd.to_datetime(nn_df["date"]).max().normalize()
        filtered = nn_df[pd.to_datetime(nn_df["date"]) >= latest]
    else:
        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        filtered = nn_df[nn_df["date"] >= cutoff]
    if filtered.empty:
        return {}
    grp = filtered.groupby("symbol")[["buy_value", "sell_value"]].sum()
    out = {}
    for sym, row in grp.iterrows():
        out[sym] = {
            "buy": round(float(row["buy_value"]) / 1e9, 1),
            "sell": round(float(row["sell_value"]) / 1e9, 1),
        }
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _compute_gtgd_by_window(window_days: int) -> dict:
    """
    Compute total GTGD (trading value, tỷ VND) per ticker over the given
    number of *trading* days using warehouse parquet (close × volume).

    window_days=0 → most recent session only (1D snapshot).
    window_days>0 → sum across last N trading days (e.g. 5 or 20).

    Cache 10 min; invalidated by @st.cache_data signature + window arg.
    """
    import pyarrow.parquet as pq
    prices_dir = Path("data_warehouse") / "prices"
    if not prices_dir.exists():
        return {}
    # Limit how many recent years we read to keep cost bounded.
    year_limit = 2 if window_days <= 30 else 3
    result: dict[str, float] = {}
    for td in prices_dir.glob("ticker=*"):
        ticker = td.name.split("=", 1)[1]
        if not ticker.isalpha() or len(ticker) > 5:
            continue
        try:
            frames = []
            for yd in sorted(td.glob("year=*"))[-year_limit:]:
                for pf in yd.glob("*.parquet"):
                    frames.append(pq.read_table(
                        str(pf), columns=["time", "close", "volume"]
                    ).to_pandas())
            if not frames:
                continue
            df = pd.concat(frames)
            df["time"] = pd.to_datetime(df["time"])
            df["_date"] = df["time"].dt.date
            # Deduplicate by date — keep last entry per day to avoid
            # double-counting from overlapping parquet files.
            df = df.drop_duplicates(subset=["_date"], keep="last")
            df = df.sort_values("_date")
            n = max(1, window_days) if window_days > 0 else 1
            df = df.tail(n)
            close = pd.to_numeric(df["close"], errors="coerce").fillna(0).astype(float)
            close = close.where(close > 500, close * 1000)
            vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
            gtgd_vnd = float((close * vol).sum())
            if gtgd_vnd > 0:
                result[ticker] = round(gtgd_vnd / 1e9, 1)
        except Exception:
            continue
    return result


_ORDER_CACHE_PATH = Path("data_warehouse/_meta/order_stats_cache.json")
_ORDER_CACHE_MAX_AGE = 1800  # 30 phút


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_order_stats_batch(tickers: tuple) -> dict:
    """
    Fetch order_stats() cho danh sách tickers (top GTGD).
    Return {ticker: {"big_order_score": float, "buy_sell_ratio": float}}.
    Disk cache 30 phút, Streamlit cache 30 phút.
    """
    # Disk cache
    if _ORDER_CACHE_PATH.exists():
        try:
            age = datetime.now().timestamp() - _ORDER_CACHE_PATH.stat().st_mtime
            if age < _ORDER_CACHE_MAX_AGE:
                cached = json.loads(_ORDER_CACHE_PATH.read_text(encoding="utf-8"))
                if len(cached) > 3:
                    log.info("Order stats: loaded %d tickers from disk", len(cached))
                    return cached
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Order stats cache corrupt: %s", e)

    try:
        from vnstock_data import Trading
    except ImportError:
        return {}

    result = {}
    for tk in tickers:
        try:
            t = Trading(symbol=tk)

            # order_stats: avg order size trend
            os_df = t.order_stats()
            if os_df is not None and not os_df.empty and len(os_df) >= 5:
                os_df = os_df.sort_values("trading_date").reset_index(drop=True)
                buy_vol = pd.to_numeric(os_df["total_buy_trade_volume"], errors="coerce").fillna(0)
                buy_cnt = pd.to_numeric(os_df["total_buy_trade"], errors="coerce").fillna(0)
                sell_vol = pd.to_numeric(os_df["total_sell_trade_volume"], errors="coerce").fillna(0)
                sell_cnt = pd.to_numeric(os_df["total_sell_trade"], errors="coerce").fillna(0)

                # Avg buy order size (volume per trade)
                safe_cnt = buy_cnt.replace(0, np.nan)
                avg_sizes = buy_vol / safe_cnt
                today_size = float(avg_sizes.iloc[-1]) if not np.isnan(avg_sizes.iloc[-1]) else 0
                hist_size = float(avg_sizes.iloc[:-1].mean()) if len(avg_sizes) > 1 else 0

                # BigOrder score: today vs historical avg
                if hist_size > 0 and today_size > 0:
                    big_order_score = max(-100, min(100, (today_size / hist_size - 1) * 100))
                else:
                    big_order_score = 0

                # Buy/Sell from order_stats (more accurate than bid/ask depth)
                total_buy = float(buy_vol.iloc[-1])
                total_sell = float(sell_vol.iloc[-1])
                total = total_buy + total_sell
                bs_ratio = total_buy / total if total > 0 else 0.5

                result[tk] = {
                    "big_order_score": round(big_order_score, 1),
                    "buy_sell_ratio": round(bs_ratio, 3),
                    "avg_order_today": round(today_size, 0),
                    "avg_order_hist": round(hist_size, 0),
                }
        except Exception:
            continue

    # Save to disk
    if len(result) > 3:
        try:
            _ORDER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _ORDER_CACHE_PATH.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8",
            )
            log.info("Order stats: saved %d tickers to disk", len(result))
        except (OSError, ValueError):
            pass

    return result


def _batch_load_live_quotes(tickers: list) -> dict:
    """
    Batch load tất cả quote JSON files 1 lần. Cache trong session_state.
    Return {ticker: {price, volume, gtgd, buy_ratio}}.
    """
    cache_key = "_mf_live_quotes"
    if cache_key in st.session_state:
        cached = st.session_state[cache_key]
        # Invalidate nếu quá 30 giây (live data thay đổi liên tục)
        if datetime.now().timestamp() - cached.get("_ts", 0) < 30:
            return cached

    live_dir = Path("data_warehouse/_live")
    result = {"_ts": datetime.now().timestamp()}

    for tk in tickers:
        qpath = live_dir / f"quote_{tk}.json"
        if not qpath.exists():
            continue
        try:
            q = json.loads(qpath.read_text(encoding="utf-8"))
            price = float(q.get("price", 0) or 0)
            if price <= 0:
                continue
            if price > 500:
                price /= 1000
            vol = float(q.get("volume", 0) or 0)
            gtgd = price * vol / 1e6

            # Buy/Sell ratio
            buy_ratio = 0.5
            # Method 1: volume_profile (from price_depth)
            vp = q.get("volume_profile", [])
            if vp:
                tb = sum(float(lv.get("buy_vol", 0) or 0) for lv in vp)
                ts_ = sum(float(lv.get("sell_vol", 0) or 0) for lv in vp)
                if tb + ts_ > 0:
                    buy_ratio = tb / (tb + ts_)
            else:
                # Method 2: bid/ask depth (from price_board)
                bids = q.get("bids", [])
                asks = q.get("asks", [])
                bv = sum(float(b.get("volume", 0) or 0) for b in bids if isinstance(b, dict))
                av = sum(float(a.get("volume", 0) or 0) for a in asks if isinstance(a, dict))
                if bv + av > 0:
                    buy_ratio = bv / (bv + av)

            result[tk] = {
                "price": price, "volume": vol,
                "gtgd": gtgd, "buy_ratio": buy_ratio,
            }
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            continue

    st.session_state[cache_key] = result
    return result


def _compute_money_flow_score(nn_net: float, nn_median: float,
                              buy_ratio: float,
                              big_order_score: float = 0) -> float:
    """
    Tính money flow score (-100 đến +100).
    nn_net:          NN ròng cho mã này (tỷ VND)
    nn_median:       median |NN ròng| của toàn thị trường (dùng để normalize)
    buy_ratio:       buy/sell ratio (0-1)
    big_order_score: lệnh lớn score (-100 đến +100), 0 nếu chưa có data
    """
    # NN score: clamp nn_net / median * 50
    if nn_median > 0:
        nn_score = max(-100, min(100, (nn_net / nn_median) * 50))
    else:
        nn_score = 0

    # Buy/Sell score: 0.5 → 0, 0.7 → +40, 0.3 → -40
    bs_score = max(-100, min(100, (buy_ratio - 0.5) * 200))

    # BigOrder score: đã clamp -100~100 từ _fetch_order_stats_batch
    bo_score = max(-100, min(100, big_order_score))

    # Weighted combination: 40% NN + 35% BuySell + 25% BigOrder
    return round(0.40 * nn_score + 0.35 * bs_score + 0.25 * bo_score, 1)


def _score_label(score: float) -> tuple:
    """Return (label, color_hex) cho money flow score."""
    if score > 30:
        return "VÀO", "#10b981"
    if score > 10:
        return "Vào nhẹ", "#6ee7b7"
    if score > -10:
        return "Trung lập", "#9ca3af"
    if score > -30:
        return "Ra nhẹ", "#fca5a5"
    return "RA", "#ef4444"


def _score_bar_html(score: float) -> str:
    """Render mini bar HTML cho score."""
    label, color = _score_label(score)
    width = min(abs(score), 80)
    direction = "right" if score >= 0 else "left"
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<div style="width:80px;height:14px;background:#1f2937;border-radius:7px;'
        f'position:relative;overflow:hidden">'
        f'<div style="position:absolute;{direction}:50%;width:{width/2}%;height:100%;'
        f'background:{color};border-radius:7px"></div>'
        f'<div style="position:absolute;left:50%;width:1px;height:100%;background:#4b5563">'
        f'</div></div>'
        f'<span style="color:{color};font-size:11px;font-weight:600;min-width:52px">'
        f'{label}</span></div>'
    )


# ── Subprocess launcher ──────────────────────────────────────────────────────
def launch_in_new_console(commands: list, log_filename: str = "subprocess.log") -> tuple:
    """
    Chạy một chuỗi Python script trong cửa sổ PowerShell mới (Windows)
    hoặc process nền có ghi log (non-Windows).

    Args:
      commands: list[dict], mỗi dict gồm:
        - "label": str — tiêu đề hiển thị `=== label ===`
        - "args":  list[str] — script + args, vd ["vnstock_updater.py", "--force"]
        - "stop_on_error": bool (mặc định True) — dừng chuỗi nếu step này fail
      log_filename: tên file log cho non-Windows fallback.

    Returns:
      (is_windows_console, log_path | None)
    """
    py = sys.executable
    cwd = str(Path(__file__).parent)
    if os.name == "nt":
        parts = [
            "$env:PYTHONIOENCODING='utf-8'",
            "chcp 65001 | Out-Null",
        ]
        for i, cmd in enumerate(commands):
            parts.append(f"Write-Host '=== {cmd['label']} ===' -ForegroundColor Cyan")
            quoted = " ".join(f"'{a}'" for a in cmd["args"])
            parts.append(f"& '{py}' {quoted}")
            if cmd.get("stop_on_error", True) and i < len(commands) - 1:
                parts.append(
                    "if ($LASTEXITCODE -ne 0) { "
                    "Write-Host 'Previous step failed' -ForegroundColor Red; "
                    "Read-Host 'Nhan Enter de dong cua so'; exit 1 }"
                )
        parts.append("Write-Host ''")
        parts.append("Read-Host 'Hoan tat. Nhan Enter de dong cua so'")
        ps_cmd = "; ".join(parts)
        subprocess.Popen(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            cwd=cwd,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True, None
    # Non-Windows fallback: chạy command đầu tiên ở background, log ra file
    log_path = Path(cwd) / log_filename
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with open(log_path, "w") as lf:
        subprocess.Popen(
            [py, *commands[0]["args"]],
            stdout=lf, stderr=subprocess.STDOUT,
            cwd=cwd, env=env,
        )
    return False, log_path


# Theme — dark mode đã là default, light mode override CSS
THEMES = {
    "light": {
        "bg": "#f8fafc", "card_bg": "#ffffff", "border": "#e2e8f0",
        "text": "#1e293b", "text2": "#475569", "text3": "#94a3b8",
    },
}

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
def _normalize_price_units(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize đơn vị giá về nghìn VND.

    vnstock (free VCI) trả giá ở nghìn VND: FPT = 77.7
    vnstock_data (sponsor) trả giá ở VND:   FPT = 77700

    Warehouse + bars parquet có thể pha trộn cả 2 đơn vị, thậm chí
    trong cùng 1 row (open=77.8 nghìn, close=77700 VND).

    Rule: không có mã nào trên sàn VN giá > 500 nghìn VND (500,000 VND).
    Vậy bất kỳ giá OHLC nào > 500 chắc chắn là VND → chia 1000.
    """
    if df.empty:
        return df

    df = df.copy()
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            continue
        vals = df[col].astype(float)
        mask = vals > 500
        if mask.any():
            df.loc[mask, col] = vals[mask] / 1000

    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_price_history(ticker: str, days: int = 0) -> pd.DataFrame:
    """Load lịch sử giá. days=0 → toàn bộ lịch sử. Cached 5 phút."""
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
    df = df.sort_values("time").reset_index(drop=True)

    # Normalize mixed price units (nghìn VND vs VND)
    df = _normalize_price_units(df)

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

    # RSI 14 — when loss is 0 (all-up streak), force RSI=100 instead of NaN.
    # The naive `loss.replace(0, NaN)` leaves gaps at the END of the series,
    # which makes the chart panel auto-fit to a shorter range than candles.
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    df["rsi"] = rsi.where(loss != 0, 100.0)

    # EMAs — chỉ tính khi đủ data (tránh EMA chưa hội tụ trên data ngắn)
    for span in (9, 21, 50, 200):
        if len(c) >= span:
            df[f"ema{span}"] = c.ewm(span=span, adjust=False).mean()
        else:
            df[f"ema{span}"] = np.nan

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

    # VWAP — Volume Weighted Average Price (chỉ có ý nghĩa cho intraday)
    # VWAP PHẢI reset mỗi ngày giao dịch (cumulative trong ngày, không qua ngày).
    _is_intraday = len(df) > 50 and (df["time"].iloc[-1] - df["time"].iloc[-2]).total_seconds() < 7200
    if _is_intraday:
        tp = (df["high"].astype(float) + df["low"].astype(float) + c) / 3
        vol = df["volume"].astype(float).replace(0, np.nan)

        # Group by date → cumulative VWAP reset mỗi ngày
        dates = df["time"].dt.date
        cum_tp_vol = (tp * vol).groupby(dates).cumsum()
        cum_vol = vol.groupby(dates).cumsum()
        df["vwap"] = cum_tp_vol / cum_vol

        # VWAP bands: ±1σ, ±2σ (cũng reset mỗi ngày)
        vwap_dev = (((tp - df["vwap"]) ** 2) * vol).groupby(dates).cumsum() / cum_vol
        vwap_std = np.sqrt(vwap_dev)
        df["vwap_upper1"] = df["vwap"] + vwap_std
        df["vwap_lower1"] = df["vwap"] - vwap_std
        df["vwap_upper2"] = df["vwap"] + 2 * vwap_std
        df["vwap_lower2"] = df["vwap"] - 2 * vwap_std

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
ALERTS_PATH = Path("data_warehouse/_meta/price_alerts.json")


def load_live_quote(ticker: str) -> dict | None:
    """Đọc live quote snapshot từ Tầng 1 (vnstock_wss)."""
    path = LIVE_DIR / f"quote_{ticker.upper()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Live quote %s corrupt: %s", ticker, e)
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Alert System
# ═════════════════════════════════════════════════════════════════════════════

def load_alerts() -> list[dict]:
    """Load price alerts từ JSON file."""
    if not ALERTS_PATH.exists():
        return []
    try:
        return json.loads(ALERTS_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Alerts file corrupt: %s", e)
        return []


def save_alerts(alerts: list[dict]):
    """Save price alerts (atomic write)."""
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    import os
    tmp = ALERTS_PATH.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(alerts, indent=2, ensure_ascii=False))
        os.replace(str(tmp), str(ALERTS_PATH))
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def send_telegram_alert(bot_token: str, chat_id: str, message: str) -> bool:
    """Gửi alert qua Telegram Bot API."""
    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def check_and_fire_alerts(alerts: list[dict], bot_token: str = "",
                          chat_id: str = "") -> list[dict]:
    """
    Check tất cả alerts, fire những cái triggered.
    Returns: list alerts đã update (triggered ones marked).
    """
    from datetime import datetime
    updated = []
    fired_messages = []

    for alert in alerts:
        ticker = alert.get("ticker", "")
        if not ticker or alert.get("fired"):
            updated.append(alert)
            continue

        q = load_live_quote(ticker)
        if not q:
            updated.append(alert)
            continue

        price = float(q.get("price", 0))
        if price <= 0:
            updated.append(alert)
            continue

        triggered = False
        condition = alert.get("condition", "")
        target = float(alert.get("target", 0))

        if condition == "above" and price >= target:
            triggered = True
        elif condition == "below" and price <= target:
            triggered = True
        elif condition == "change_up":
            chg = float(q.get("chg_pct", 0))
            if chg >= target:
                triggered = True
        elif condition == "change_down":
            chg = float(q.get("chg_pct", 0))
            if chg <= -target:
                triggered = True
        elif condition == "volume_above":
            vol = float(q.get("volume", 0))
            if vol >= target:
                triggered = True

        if triggered:
            alert["fired"] = True
            alert["fired_at"] = datetime.now().isoformat(timespec="seconds")
            alert["fired_price"] = price

            cond_desc = {
                "above": f"giá >= {target:,.0f}",
                "below": f"giá <= {target:,.0f}",
                "change_up": f"tăng >= {target:.1f}%",
                "change_down": f"giảm >= {target:.1f}%",
                "volume_above": f"volume >= {target:,.0f}",
            }.get(condition, condition)

            msg = (
                f"🔔 <b>ALERT: {ticker}</b>\n"
                f"Điều kiện: {cond_desc}\n"
                f"Giá hiện tại: {price:,.2f}\n"
                f"Thời gian: {alert['fired_at']}"
            )
            fired_messages.append(msg)
            alert["message"] = msg

        updated.append(alert)

    # Gửi Telegram nếu có config
    if fired_messages and bot_token and chat_id:
        for msg in fired_messages:
            send_telegram_alert(bot_token, chat_id, msg)

    return updated


# ═════════════════════════════════════════════════════════════════════════════
# Portfolio Tracker
# ═════════════════════════════════════════════════════════════════════════════





def list_live_futures() -> list[str]:
    """
    Quét thư mục _live để tìm futures đang có live data.
    Prefer friendly names (VN30F1M, ...) vì chứa volume_profile.
    Nếu không có friendly name nào, fallback sang internal IDs (41I*).
    """
    if not LIVE_DIR.exists():
        return []
    friendly = []
    internal = []
    for p in sorted(LIVE_DIR.glob("quote_*.json")):
        name = p.stem.replace("quote_", "")
        if not is_futures(name):
            continue
        if name.startswith("VN30F"):
            friendly.append(name)
        elif name.startswith("41I"):
            internal.append(name)
    # Priority: friendly first (có VP). Internal chỉ để user tham khảo.
    return friendly if friendly else internal


@st.cache_data(ttl=10, show_spinner=False)
def fetch_volume_profile_direct(ticker: str) -> list:
    """
    Fetch Volume Profile trực tiếp từ Quote.price_depth() — on-demand.
    Cache 10 giây để tránh spam API khi user refresh liên tục.
    Dùng cho stocks (thay vì WSS cycle). Futures vẫn dùng WSS.
    """
    try:
        from vnstock_data import Quote
        q = Quote(symbol=ticker)
        df = None
        for call in (
            lambda: q.price_depth(),
            lambda: q.price_depth(limit=50),
        ):
            try:
                df = call()
                if df is not None and hasattr(df, "empty") and not df.empty:
                    break
            except TypeError:
                continue
            except Exception:
                continue

        if df is None or not hasattr(df, "empty") or df.empty:
            return []

        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        if "price" not in df.columns or "totalvol" not in df.columns:
            return []

        profile = []
        for _, row in df.iterrows():
            try:
                profile.append({
                    "price": float(row["price"]),
                    "buy_vol": float(row.get("buyvol", 0) or 0),
                    "sell_vol": float(row.get("sellvol", 0) or 0),
                    "unknown_vol": float(row.get("unknownvol", 0) or 0),
                    "total_vol": float(row.get("totalvol", 0) or 0),
                })
            except Exception:
                continue

        if not profile:
            return []

        # Top 20 theo total_vol, sort theo price giảm dần
        profile.sort(key=lambda r: r["total_vol"], reverse=True)
        top = profile[:20]
        top.sort(key=lambda r: r["price"], reverse=True)
        return top
    except Exception:
        return []


def _calc_value_area(profile: list, pct: float = 0.70) -> tuple:
    """
    Tính Value Area — vùng giá chứa `pct` (mặc định 70%) tổng volume.

    Thuật toán:
    1. Tìm POC (price level có total_vol cao nhất)
    2. Từ POC, mở rộng ra 2 bên (trên + dưới) — mỗi bước chọn bên nào
       có volume cao hơn
    3. Dừng khi tổng volume trong vùng đạt ≥ pct × total_all_vol

    Returns: (poc_idx, vah_idx, val_idx, poc_price, vah_price, val_price)
      trong đó idx là index trong list profile (đã sort theo price giảm dần).
    """
    if not profile:
        return (0, 0, 0, 0, 0, 0)

    # Profile đã sort theo price giảm dần
    volumes = [float(r.get("total_vol", 0)) for r in profile]
    prices = [float(r.get("price", 0)) for r in profile]
    total_all = sum(volumes)
    if total_all <= 0:
        return (0, 0, len(profile) - 1, prices[0], prices[0],
                prices[-1] if prices else 0)

    # POC = index có volume cao nhất
    poc_idx = max(range(len(volumes)), key=lambda i: volumes[i])

    # Mở rộng từ POC ra 2 bên
    va_vol = volumes[poc_idx]
    target = total_all * pct
    upper = poc_idx - 1   # index nhỏ hơn = price cao hơn (sort giảm dần)
    lower = poc_idx + 1   # index lớn hơn = price thấp hơn

    while va_vol < target and (upper >= 0 or lower < len(volumes)):
        up_vol = volumes[upper] if upper >= 0 else -1
        lo_vol = volumes[lower] if lower < len(volumes) else -1

        if up_vol >= lo_vol and upper >= 0:
            va_vol += up_vol
            upper -= 1
        elif lower < len(volumes):
            va_vol += lo_vol
            lower += 1
        else:
            break

    vah_idx = max(upper + 1, 0)
    val_idx = min(lower - 1, len(volumes) - 1)

    return (poc_idx, vah_idx, val_idx,
            prices[poc_idx], prices[vah_idx], prices[val_idx])


def render_volume_profile(profile: list, current_price: float = 0,
                          scale: float = 1.0, max_rows: int = 20):
    """
    Render Volume Profile — bảng top N mức giá có khớp lệnh nhiều nhất
    trong phiên, kèm breakdown buy / sell / unknown volume.

    Features:
    - POC (Point of Control): highlight mức giá có volume cao nhất
    - Value Area (70%): tô nền các dòng trong VA, hiện VAH/VAL
    - Delta: cột buy-sell delta, tích luỹ delta, color coding

    profile: list of {price, buy_vol, sell_vol, unknown_vol, total_vol}
      đã sort theo price (giảm dần)
    current_price: giá hiện tại để highlight dòng tương ứng
    scale: chia giá cho scale nếu cần normalize
    """
    if not profile:
        return

    display = profile[:max_rows]

    # ── Tính POC + Value Area ──
    poc_idx, vah_idx, val_idx, poc_price, vah_price, val_price = \
        _calc_value_area(display)

    max_total = max((float(r.get("total_vol", 0)) for r in display), default=1)
    if max_total <= 0:
        max_total = 1

    # Max delta để scale delta bar
    deltas = []
    for r in display:
        bv = float(r.get("buy_vol", 0))
        sv = float(r.get("sell_vol", 0))
        deltas.append(bv - sv)
    max_abs_delta = max((abs(d) for d in deltas), default=1) or 1

    # Cumulative delta (tích luỹ từ giá thấp → cao = bottom → top)
    cum_deltas = [0.0] * len(display)
    cum = 0.0
    for i in range(len(display) - 1, -1, -1):   # từ low lên high
        cum += deltas[i]
        cum_deltas[i] = cum

    rows_html = ""
    for i, r in enumerate(display):
        try:
            price = float(r.get("price", 0))
            buy_v = float(r.get("buy_vol", 0))
            sell_v = float(r.get("sell_vol", 0))
            total_v = float(r.get("total_vol", 0))
        except Exception:
            continue

        delta = deltas[i]
        cum_d = cum_deltas[i]
        pct = total_v / max_total * 100
        price_str = f"{price / scale:,.2f}"

        is_current = current_price > 0 and abs(price - current_price) < 0.01
        is_poc = (i == poc_idx)
        in_va = (vah_idx <= i <= val_idx)

        # Row background: POC > current price > Value Area > default
        if is_poc:
            row_bg = "background:rgba(251,191,36,0.25)"
        elif is_current:
            row_bg = "background:rgba(251,191,36,0.10)"
        elif in_va:
            row_bg = "background:rgba(59,130,246,0.08)"
        else:
            row_bg = ""

        # Price label
        label = ""
        if is_poc:
            label = " <span style='color:#fbbf24;font-size:9px;font-weight:700'>POC</span>"
        elif i == vah_idx and vah_idx != poc_idx:
            label = " <span style='color:#3b82f6;font-size:9px;font-weight:600'>VAH</span>"
        elif i == val_idx and val_idx != poc_idx:
            label = " <span style='color:#3b82f6;font-size:9px;font-weight:600'>VAL</span>"

        buy_pct = (buy_v / total_v * 100) if total_v > 0 else 0
        sell_pct = (sell_v / total_v * 100) if total_v > 0 else 0

        # Delta bar — xanh nếu >0, đỏ nếu <0
        delta_width = abs(delta) / max_abs_delta * 50  # max 50% width
        delta_color = "#10b981" if delta >= 0 else "#ef4444"
        delta_sign = "+" if delta >= 0 else ""
        delta_str = f"{delta_sign}{int(delta):,}"

        # Cumulative delta color
        cum_color = "#10b981" if cum_d >= 0 else "#ef4444"
        cum_sign = "+" if cum_d >= 0 else ""
        cum_str = f"{cum_sign}{int(cum_d):,}"

        rows_html += (
            f"<tr style='{row_bg}'>"
            # Price + label
            f"<td style='color:#f9fafb;text-align:right;padding:4px 8px;"
            f"font-weight:{'700' if is_poc or is_current else '500'};white-space:nowrap'>"
            f"{price_str}{label}</td>"
            # Buy
            f"<td style='color:#10b981;text-align:right;padding:4px 8px'>"
            f"{int(buy_v):,}</td>"
            # Sell
            f"<td style='color:#ef4444;text-align:right;padding:4px 8px'>"
            f"{int(sell_v):,}</td>"
            # Total
            f"<td style='color:#9ca3af;text-align:right;padding:4px 8px'>"
            f"{int(total_v):,}</td>"
            # Delta (buy - sell)
            f"<td style='color:{delta_color};text-align:right;padding:4px 8px;"
            f"font-size:11px'>"
            f"<div style='display:flex;align-items:center;justify-content:flex-end;gap:4px'>"
            f"<span>{delta_str}</span>"
            f"<div style='width:50px;height:10px;background:#1f2937;border-radius:1px;"
            f"position:relative;overflow:hidden'>"
            f"<div style='position:absolute;{'right' if delta < 0 else 'left'}:0;top:0;"
            f"height:100%;width:{delta_width:.1f}%;background:{delta_color};opacity:0.7'>"
            f"</div></div></div></td>"
            # Cumulative Delta
            f"<td style='color:{cum_color};text-align:right;padding:4px 8px;"
            f"font-size:11px'>{cum_str}</td>"
            # Distribution bar
            f"<td style='padding:4px 8px;min-width:100px'>"
            f"<div style='position:relative;height:14px;background:#1f2937;"
            f"border-radius:2px;overflow:hidden'>"
            f"<div style='position:absolute;left:0;top:0;height:100%;"
            f"width:{buy_pct * pct / 100:.1f}%;background:#10b981'></div>"
            f"<div style='position:absolute;left:{buy_pct * pct / 100:.1f}%;top:0;"
            f"height:100%;width:{sell_pct * pct / 100:.1f}%;background:#ef4444'></div>"
            f"</div></td>"
            f"</tr>"
        )

    # ── Summary line: POC / VAH / VAL ──
    summary_parts = [
        f"<span style='color:#fbbf24'>■</span> POC {poc_price/scale:,.2f}",
    ]
    if vah_idx != val_idx:
        summary_parts.append(
            f"<span style='color:#3b82f6'>■</span> "
            f"VA [{val_price/scale:,.2f} — {vah_price/scale:,.2f}]"
        )

    # Total cumulative delta
    total_cum = cum_deltas[0] if cum_deltas else 0
    cum_total_color = "#10b981" if total_cum >= 0 else "#ef4444"
    cum_total_sign = "+" if total_cum >= 0 else ""
    summary_parts.append(
        f"Σ Delta <span style='color:{cum_total_color}'>"
        f"{cum_total_sign}{int(total_cum):,}</span>"
    )

    html = (
        f"<div style='margin:14px 0'>"
        f"<div style='color:#9ca3af;font-size:11px;margin-bottom:6px;"
        f"text-transform:uppercase;letter-spacing:0.08em;font-weight:500'>"
        f"📊 Volume Profile — Top {min(len(profile), max_rows)} mức giá sôi động "
        f"(cả phiên)</div>"
        f"<table style='width:100%;font-family:IBM Plex Mono,monospace;"
        f"font-size:12px;border-collapse:collapse;"
        f"border:1px solid #1f2937;border-radius:6px;overflow:hidden'>"
        f"<thead><tr style='color:#6b7280;font-size:10px;"
        f"text-transform:uppercase;letter-spacing:0.05em;background:#111827'>"
        f"<th style='text-align:right;padding:6px 8px'>Giá</th>"
        f"<th style='text-align:right;padding:6px 8px'>Mua</th>"
        f"<th style='text-align:right;padding:6px 8px'>Bán</th>"
        f"<th style='text-align:right;padding:6px 8px'>Tổng</th>"
        f"<th style='text-align:right;padding:6px 8px'>Delta</th>"
        f"<th style='text-align:right;padding:6px 8px'>Σ Delta</th>"
        f"<th style='text-align:left;padding:6px 8px'>Phân bổ</th>"
        f"</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
        f"<div style='color:#6b7280;font-size:10px;margin-top:4px'>"
        f"{' &nbsp;|&nbsp; '.join(summary_parts)}"
        f"</div>"
        f"<div style='color:#6b7280;font-size:9px;margin-top:2px'>"
        f"<span style='color:#fbbf24'>█</span> POC &nbsp; "
        f"<span style='color:#3b82f6;opacity:0.5'>█</span> Value Area 70% &nbsp; "
        f"<span style='color:#10b981'>■</span> Mua &nbsp; "
        f"<span style='color:#ef4444'>■</span> Bán &nbsp; "
        f"Delta = Mua − Bán &nbsp; Σ = tích luỹ từ giá thấp"
        f"</div>"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


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
def _get_wss_singleton(full_market: bool = True):
    """Singleton WSS client — start once per Streamlit process."""
    if not WSS_AVAILABLE:
        return None
    try:
        client = get_wss_client()
        client.start()
        client.subscribe_all(full_market=full_market)
        return client
    except Exception as e:
        print(f"[dashboard] WSS start failed: {e}")
        return None


@st.cache_data(ttl=120, show_spinner=False)
def load_intraday_bars(ticker: str, target_date: str = None) -> pd.DataFrame:
    """
    Load 1m bars từ parquet (live hoặc archive).
    Dùng cho intraday chart replay sau phiên.

    target_date: "YYYY-MM-DD" — nếu None, dùng hôm nay.
    Returns: DataFrame [time, open, high, low, close, volume] cho 1 ticker.
    """
    from pathlib import Path
    if target_date is None:
        from datetime import date
        target_date = date.today().isoformat()

    # Tìm file: live trước, archive sau
    bars_name = f"bars_{target_date}.parquet"
    candidates = [
        Path("data_warehouse/_live") / bars_name,
        Path("data_warehouse/_live/archive") / bars_name,
    ]

    bars_path = None
    for p in candidates:
        if p.exists():
            bars_path = p
            break

    if bars_path is None:
        return pd.DataFrame()

    try:
        import pyarrow.parquet as pq
        df = pq.read_table(str(bars_path)).to_pandas()
        if df.empty:
            return pd.DataFrame()

        # Filter theo ticker
        if "ticker" in df.columns:
            df = df[df["ticker"].str.upper() == ticker.upper()].copy()

        if df.empty:
            return pd.DataFrame()

        needed = ["time", "open", "high", "low", "close", "volume"]
        for c in needed:
            if c not in df.columns:
                return pd.DataFrame()

        df = df[needed].copy()
        df["time"] = pd.to_datetime(df["time"])
        # Lọc giờ giao dịch
        mask = (df["time"].dt.hour >= 9) & (df["time"].dt.hour < 15)
        df = df[mask]
        df = df.sort_values("time").reset_index(drop=True)
        # Normalize price units nếu có pha trộn
        df = _normalize_price_units(df)
        return df
    except Exception as e:
        print(f"[load_intraday_bars] {ticker} {target_date}: {e}")
        return pd.DataFrame()


def list_available_bar_dates() -> list[str]:
    """Liệt kê các ngày có bars parquet (live + archive)."""
    from pathlib import Path
    dates = set()
    for folder in [Path("data_warehouse/_live"),
                    Path("data_warehouse/_live/archive")]:
        if folder.exists():
            for f in folder.glob("bars_*.parquet"):
                # bars_2026-04-10.parquet → 2026-04-10
                name = f.stem  # bars_2026-04-10
                date_part = name.replace("bars_", "")
                if len(date_part) == 10:  # YYYY-MM-DD
                    dates.add(date_part)
    return sorted(dates, reverse=True)


@st.cache_data(ttl=60, show_spinner=False)
def load_intraday(ticker: str, interval: str = "15m") -> pd.DataFrame:
    """Fetch intraday OHLCV từ VCI. interval: '1m','5m','15m','30m','1H'"""
    try:
        from datetime import date as _d, timedelta as _td
        lookback = {"1m":5,"5m":30,"15m":60,"30m":60,"1H":90}.get(interval, 10)
        end   = _d.today().strftime("%Y-%m-%d")
        start = (_d.today() - _td(days=lookback)).strftime("%Y-%m-%d")
        # Use vnstock 4.x Quote API (vnstock.explorer path removed in 4.x)
        try:
            from vnstock_auth import get_vnstock
            df = get_vnstock(ticker).quote.history(
                start=start, end=end, interval=interval)
        except Exception:
            try:
                from vnstock.explorer.vci.quote import Quote as _VCIQuote
                _q = _VCIQuote(symbol=ticker, show_log=False)
                df = _q.history(start=start, end=end, interval=interval)
            except Exception:
                df = None
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


_FUND_CACHE_DIR = Path("data_warehouse/_meta/fund_cache")
_FUND_CACHE_VER = 4


def _get_warehouse_last_close(ticker: str) -> float | None:
    """Read last close price (VND) from warehouse parquet for a single ticker."""
    import pyarrow.parquet as pq
    td = Path("data_warehouse") / "prices" / f"ticker={ticker.upper()}"
    if not td.exists():
        return None
    try:
        for yd in sorted(td.glob("year=*"))[-1:]:
            for pf in sorted(yd.glob("*.parquet"))[-1:]:
                df = pq.read_table(str(pf), columns=["close"]).to_pandas()
                if not df.empty:
                    close = float(df["close"].iloc[-1])
                    if 0 < close <= 500:
                        close *= 1000
                    return close if close > 0 else None
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_fundamental(ticker: str) -> dict:
    """Load comprehensive fundamental data from vnstock.
    Fetches company.overview() + finance.ratio() for maximum coverage.
    Disk-cached per ticker (24h), Streamlit-cached (1h).
    """
    # Disk cache: 24 giờ — fundamental data thay đổi chậm
    _fpath = _FUND_CACHE_DIR / f"{ticker.upper()}.json"
    if _fpath.exists():
        try:
            age = datetime.now().timestamp() - _fpath.stat().st_mtime
            if age < 86400:  # 24 giờ
                cached = json.loads(_fpath.read_text(encoding="utf-8"))
                if cached.get("_cache_ver") == _FUND_CACHE_VER:
                    return cached
        except (OSError, json.JSONDecodeError):
            pass

    result = {}
    try:
        from vnstock_auth import ensure_api_key
        ensure_api_key()

        # Ưu tiên vnstock_data sponsor (ổn định, không KeyError: 'data')
        _stock = None
        _use_sponsor = False
        try:
            from vnstock_data import Company as _Company, Finance as _Finance
            _company = _Company(symbol=ticker)
            # Finance cần source param
            try:
                _finance = _Finance(symbol=ticker, source="VCI")
            except TypeError:
                _finance = _Finance(symbol=ticker)
            _use_sponsor = True
        except Exception:
            try:
                from vnstock_auth import get_vnstock
                _stock = get_vnstock(ticker)
            except Exception:
                pass

        # ── 1. Company Overview — market cap, shares, EPS, P/E, etc. ─────
        try:
            overview = _company.overview() if _use_sponsor else _stock.company.overview()
            if overview is not None and not overview.empty:
                row = overview.iloc[0] if len(overview) > 0 else None
                if row is not None:
                    def _ov(df_row, *keys):
                        # Strip parens content (e.g. "EPS (VND)" → "eps") so
                        # short keys still match exactly. Also drop common
                        # punctuation that varies across sources.
                        import re as _re
                        def _norm(s: str) -> str:
                            s = str(s).lower()
                            s = _re.sub(r"\([^)]*\)", "", s)
                            for ch in (" ", "_", "/", "-", ".", "%", ",", "(", ")"):
                                s = s.replace(ch, "")
                            return s
                        col_cache = [(_c, _norm(str(_c))) for _c in overview.columns]

                        def _try(col_name):
                            try:
                                v = df_row[col_name]
                                if v is not None and not pd.isna(v):
                                    return float(v)
                            except Exception:
                                pass
                            return None

                        # Pass 1: exact match
                        for k in keys:
                            kl = _norm(k)
                            for col, cl in col_cache:
                                if cl == kl:
                                    v = _try(col)
                                    if v is not None:
                                        return v
                        # Pass 2: prefix/suffix match
                        for k in keys:
                            kl = _norm(k)
                            for col, cl in col_cache:
                                if cl.startswith(kl) or cl.endswith(kl):
                                    v = _try(col)
                                    if v is not None:
                                        return v
                        # Pass 3: substring (only keys >= 5 chars to avoid false positives)
                        for k in keys:
                            kl = _norm(k)
                            if len(kl) < 5:
                                continue
                            for col, cl in col_cache:
                                if kl in cl:
                                    v = _try(col)
                                    if v is not None:
                                        return v
                        return None

                    result["market_cap"] = _ov(row, "vonhoathitruong", "marketcap", "market_cap")
                    result["shares_outstanding"] = _ov(row, "klcpluuhanh", "sharesoutstanding", "outstanding")
                    result["shares_listed"] = _ov(row, "klcpniemyet", "shareslisted", "issueshare")
                    result["avg_vol_10"] = _ov(row, "khoplenh10phien", "avgvolume", "avg_vol", "averagevolume")
                    result["pe"] = _ov(row, "pe", "pricetoearning")
                    result["pb"] = _ov(row, "pb", "pricetobook")
                    result["eps"] = _ov(row, "eps", "earningpershare")
                    result["book_value"] = _ov(row, "giatrisosach", "bookvalue", "bvps")
                    result["dividend_yield"] = _ov(row, "tysuatcotuc", "dividendyield")

                    # Sanity checks — reject obviously wrong values
                    if result.get("pe") is not None and abs(result["pe"]) > 500:
                        result["pe"] = None
                    if result.get("pb") is not None and abs(result["pb"]) > 100:
                        result["pb"] = None
                    if result.get("eps") is not None and abs(result["eps"]) > 1e6:
                        result["eps"] = None

                    result["_overview_cols"] = [str(c) for c in overview.columns[:30]]
        except Exception:
            pass

        # ── 2. Finance Ratios — ROE, ROA, margins, growth, etc. ──────────
        try:
            ratios = None
            for _kw in [
                {"period": "year", "lang": "vi"},
                {"period": "year", "lang": "en"},
                {"period": "year"},
                {"period": "annual"},
                {"period": "quarter", "lang": "vi"},
            ]:
                try:
                    if _use_sponsor:
                        ratios = _finance.ratio(**_kw)
                    else:
                        ratios = _stock.finance.ratio(**_kw)
                    if ratios is not None and not ratios.empty:
                        break
                except Exception:
                    continue

            if ratios is not None and not ratios.empty:
                # Flatten MultiIndex columns to strings for reliable matching.
                # VCI returns tuples like ("Định giá", "P/E") — flatten to
                # "Định giá_P/E" so _norm matching works consistently.
                if isinstance(ratios.columns, pd.MultiIndex):
                    ratios.columns = [
                        "_".join(str(c) for c in col if str(c) not in ("", "nan")).strip("_")
                        for col in ratios.columns
                    ]
                else:
                    ratios.columns = [
                        "_".join(str(c) for c in col).strip("_") if isinstance(col, tuple)
                        else str(col)
                        for col in ratios.columns
                    ]

                # Try up to 3 most-recent rows (iloc[0] may have NaN for
                # some fields — e.g. partial-year data).
                _ratio_rows = [ratios.iloc[i] for i in range(min(3, len(ratios)))]
                skip = ("year", "năm", "period", "quarter", "quý",
                        "index", "ticker", "symbol", "len")

                def _rv(*keys):
                    import re as _re
                    def _norm(s: str) -> str:
                        s = str(s).lower()
                        s = _re.sub(r"\([^)]*\)", "", s)
                        for ch in (" ", "_", "/", "-", ".", "%", ",", "(", ")"):
                            s = s.replace(ch, "")
                        return s
                    col_cache = []
                    for col in ratios.columns:
                        cc = _norm(str(col))
                        if any(sp in cc for sp in skip):
                            continue
                        col_cache.append((col, cc))

                    def _try_rv(col_name):
                        for rrow in _ratio_rows:
                            try:
                                v = rrow[col_name]
                                if v is not None and not pd.isna(v):
                                    fv = float(v)
                                    if abs(fv) > 1e9:
                                        continue
                                    return fv
                            except Exception:
                                continue
                        return None

                    # Pass 1: exact match
                    for k in keys:
                        kl = _norm(k)
                        for col, cc in col_cache:
                            if cc == kl:
                                v = _try_rv(col)
                                if v is not None:
                                    return v
                    # Pass 2: prefix/suffix
                    for k in keys:
                        kl = _norm(k)
                        for col, cc in col_cache:
                            if cc.startswith(kl) or cc.endswith(kl):
                                v = _try_rv(col)
                                if v is not None:
                                    return v
                    # Pass 3: substring (long keys only)
                    for k in keys:
                        kl = _norm(k)
                        if len(kl) < 5:
                            continue
                        for col, cc in col_cache:
                            if kl in cc:
                                v = _try_rv(col)
                                if v is not None:
                                    return v
                    return None

                # Only fill if overview didn't provide.
                # Keys include actual VCI Vietnamese column names after _norm:
                #   'Biên LN gộp (%)' → "biênlngộp"
                #   'Biên LN sau thuế (%)' → "biênlnsauthuế"
                #   'Biên EBIT (%)' → "biênebit"
                #   'Nợ/Vốn chủ' → "nợvốnchủ"
                #   'Tỷ suất cổ tức (%)' → "tỷsuấtcổtức"
                if result.get("pe") is None:
                    result["pe"] = _rv("pe", "pricetoearning")
                if result.get("pb") is None:
                    result["pb"] = _rv("pb", "pricetobook")
                if result.get("eps") is None:
                    result["eps"] = _rv("eps", "earningpershare")
                if result.get("book_value") is None:
                    result["book_value"] = _rv("bvps", "bookvaluepershare", "giátrịsổsách")
                if result.get("market_cap") is None:
                    _rmcap = _rv("vốnhóa")
                    if _rmcap and _rmcap > 0:
                        result["market_cap"] = _rmcap
                if result.get("dividend_yield") is None:
                    result["dividend_yield"] = _rv("tỷsuấtcổtức", "dividendyield")
                result["roe"] = _rv("roe", "returnonequity")
                result["roa"] = _rv("roa", "returnonasset")
                result["net_margin"] = _rv("biênlnsauthuế", "biênlãithuần", "biênlợinhuậnròng",
                                            "netmargin", "netprofitmargin")
                result["gross_margin"] = _rv("biênlngộp", "biênlợinhuậngộp",
                                              "grossmargin", "grossprofitmargin")
                result["operating_margin"] = _rv("biênebit", "biênlợinhuậnhoạtđộng",
                                                  "operatingmargin", "ebitmargin")
                result["debt_ratio"] = _rv("nợtổngtàisản", "debttoasset", "debtratio")
                result["debt_to_equity"] = _rv("nợvốnchủ", "nợtrênvốnchủ",
                                                "debttoequity", "đònbẩytàichính")
                result["current_ratio"] = _rv("thanhtoánhiệnhành", "currentratio")
                result["quick_ratio"] = _rv("thanhtoánnhanh", "quickratio", "acidtest")
                result["asset_turnover"] = _rv("vòngquaytàisản", "assetturnover", "totalassetturnover")
                result["revenue_growth"] = _rv("tăngtrưởngdoanhthu", "revenuegrowth")
                result["profit_growth"] = _rv("tăngtrưởnglợinhuận", "profitgrowth", "netincomegrowth")

                # Convert ratio to percentage
                for key in ("roe", "roa", "net_margin", "gross_margin", "operating_margin",
                             "dividend_yield", "revenue_growth", "profit_growth"):
                    if result.get(key) is not None and abs(result[key]) <= 2:
                        result[key] = round(result[key] * 100, 2)

                # Derive EPS and BVPS from P/E, P/B + warehouse last close
                # when VCI ratio data doesn't include an EPS column.
                if result.get("eps") is None or result.get("book_value") is None:
                    _last_close = _get_warehouse_last_close(ticker)
                    if _last_close and _last_close > 0:
                        if result.get("eps") is None and result.get("pe") and result["pe"] > 0:
                            result["eps"] = round(_last_close / result["pe"], 2)
                        if result.get("book_value") is None and result.get("pb") and result["pb"] > 0:
                            result["book_value"] = round(_last_close / result["pb"], 2)

                # Derived: Earnings yield (%) = 100/PE when PE>0
                if result.get("pe") and result["pe"] > 0:
                    result["earnings_yield"] = round(100.0 / result["pe"], 2)

                result["_ratio_cols"] = [str(c) for c in ratios.columns[:30]]
        except Exception:
            pass

    except Exception as e:
        result["error"] = str(e)[:120]

    # Persist to disk (24h cache)
    if result and "error" not in result:
        try:
            result["_cache_ver"] = _FUND_CACHE_VER
            _FUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _fpath.write_text(
                json.dumps(result, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            pass
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Market Session Stats — 4 time-window snapshots
# ═════════════════════════════════════════════════════════════════════════════
try:
    from vnstock_session_stats import (
        SESSION_WINDOWS, SESSION_INDICES,
        save_session_stats as _save_session_stats_impl,
        load_session_stats_history as _load_session_stats_impl,
    )
except Exception:
    SESSION_WINDOWS = {
        "9h-10h":   ("09:00", "10:00"),
        "9h-11h30": ("09:00", "11:30"),
        "9h-14h":   ("09:00", "14:00"),
        "9h-15h":   ("09:00", "15:00"),
    }
    SESSION_INDICES = ["VNINDEX", "VN30", "HNX", "UPCOM"]
    def _save_session_stats_impl(stats): pass
    def _load_session_stats_impl(): return {}





def save_session_stats(stats: dict):
    """Save today's session stats. Invalidates Streamlit cache after write."""
    _save_session_stats_impl(stats)
    load_session_stats_history.clear()


@st.cache_data(ttl=60, show_spinner=False)
def load_session_stats_history() -> dict:
    """Load session stats history (Streamlit-cached 60s)."""
    return _load_session_stats_impl()


def render_session_stats_table(window_name: str, stats_today: dict, history: dict,
                                mode: str = "total"):
    """
    Render a compact session stats table with 30-day history and color scale.
    Only show VOL (triệu CP) and GTGD (tỷ) per index — compact 2-column per index.

    mode: "total" (default) shows vol/gtgd including block deals;
          "matched" shows vol_matched/gtgd_matched (excludes block deals
          for cleaner cross-day comparison). Cells missing the matched
          split (today's estimate, UPCOM) fall back to total silently.
    """
    st.markdown(f"<p style='font-size:13px;font-weight:700;margin:0 0 4px'>📊 {window_name}</p>",
                unsafe_allow_html=True)

    from datetime import date, datetime
    today_str = date.today().isoformat()

    def _is_trading_day(d: str) -> bool:
        try:
            return datetime.strptime(d, "%Y-%m-%d").weekday() < 5  # Mon–Fri only
        except Exception:
            return True

    dates = sorted(
        [d for d in history.keys() if d <= today_str and _is_trading_day(d)],
        reverse=True
    )[:90]

    if today_str not in dates and stats_today and _is_trading_day(today_str):
        dates.insert(0, today_str)

    if not dates:
        st.caption("Chưa có dữ liệu")
        return

    # Determine if this window has closed for today. Used to decide
    # whether today's row should show 🟡 (still updating) or 🟢 (closed).
    _now = datetime.now()
    _end_str = SESSION_WINDOWS[window_name][1]  # e.g. "10:00"
    _end_h, _end_m = map(int, _end_str.split(":"))
    _window_closed_today = (_now.hour, _now.minute) >= (_end_h, _end_m)

    rows = []
    for d in dates:
        row = {"Ngày": d}
        if d == today_str and stats_today:
            day_stats = stats_today
        else:
            day_data = history.get(d, {})
            day_stats = day_data.get(window_name, {})

        all_zero = True
        any_data = False
        for idx in SESSION_INDICES:
            s = day_stats.get(idx, {})
            if mode == "matched":
                # Prefer matched-only fields; fall back to total when the
                # split isn't available (today's estimate cells and UPCOM
                # which lacks price_history). Falsy 0 fallback via `or`.
                vol_raw = s.get("vol_matched") or s.get("vol", 0)
                gtgd_raw = s.get("gtgd_matched") or s.get("gtgd", 0)
            else:
                vol_raw = s.get("vol", 0)
                gtgd_raw = s.get("gtgd", 0)
            vol_m = vol_raw / 1e6  # triệu CP
            gtgd = gtgd_raw
            row[f"{idx} VOL"] = round(vol_m, 1)
            row[f"{idx} GTGD"] = round(gtgd, 1)
            if vol_m > 0 or gtgd > 0:
                all_zero = False
                any_data = True

        # Drop holidays / market-closed days (all indices reporting zero).
        # Keep today's row even if zero — market may not have opened yet.
        if all_zero and d != today_str:
            continue
        # Status marker semantics:
        #   🟢 settled — past day OR (today AND window has closed)
        #   🟡 live    — today AND window still in progress (updating)
        if any_data:
            settled = (d != today_str) or _window_closed_today
            row["Ngày"] = f"{d} {'🟢' if settled else '🟡'}"
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        st.caption("Chưa có dữ liệu")
        return

    # Date column may be "YYYY-MM-DD" or "YYYY-MM-DD 🟢/🟡" — split off any
    # trailing status emoji before parsing the date, then re-attach.
    def _fmt_date_with_marker(s: str) -> str:
        parts = s.split(" ", 1)
        try:
            d = pd.to_datetime(parts[0]).strftime("%d/%m")
        except Exception:
            return s
        return f"{d} {parts[1]}" if len(parts) > 1 else d
    df["Ngày"] = df["Ngày"].astype(str).map(_fmt_date_with_marker)
    num_cols = [c for c in df.columns if c != "Ngày"]

    def _color_scale(s):
        if s.dtype not in ["float64", "int64", "float32", "int32"]:
            return [""] * len(s)
        vals = s.values.astype(float)
        pos = vals[vals > 0]
        if len(pos) == 0:
            return [""] * len(s)
        vmin, vmax = pos.min(), pos.max()
        if vmax == vmin:
            return ["background-color: rgba(250,240,140,0.25)"] * len(s)
        result = []
        for v in vals:
            if v <= 0:
                result.append("color:#6b7280")
            else:
                n = (v - vmin) / (vmax - vmin)
                if n < 0.5:
                    r, g, b = 220, int(80 + n * 2 * 160), 60
                else:
                    r, g, b = int(220 - (n - 0.5) * 2 * 180), 200, 60
                result.append(f"background-color:rgba({r},{g},{b},0.3);color:#e5e7eb")
        return result

    fmt = {c: "{:,.1f}" for c in num_cols}
    styled = (
        df.style
        .format(fmt, na_rep="—")
        .apply(_color_scale, subset=num_cols)
        .set_properties(**{"font-size": "10px", "text-align": "right", "padding": "2px 4px"})
        .set_properties(subset=["Ngày"], **{
            "text-align": "center", "font-weight": "600",
            "font-size": "10px", "min-width": "40px"
        })
    )

    _row_h = 28
    _header_h = 38
    _default_rows = 15
    _height = _row_h * _default_rows + _header_h  # fixed 15-row height, scroll for older
    st.dataframe(
        styled,
        hide_index=True,
        use_container_width=True,
        height=_height,
    )
    _mode_label = (
        "khớp lệnh (loại block deals; cells thiếu data tự fallback về tổng)"
        if mode == "matched"
        else "tổng (gồm khớp lệnh + thoả thuận)"
    )
    st.caption(
        f"VOL = triệu CP · GTGD = tỷ VND · "
        f"Loại GTGD: **{_mode_label}** · "
        "🟢 = đã chốt phiên · 🟡 = đang giao dịch (cập nhật mỗi 30s, "
        "ước tính sai số ±5%, tự sửa sau EOD)"
    )


def render_chart(df: pd.DataFrame, ticker: str, height: int = 850,
                 volume_profile: list = None, live_url: str | None = None,
                 live_poll_ms: int = 30000):
    """
    TradingView lightweight-charts — inline JS (no CDN needed).
    Fast, no weekend gaps, synced crosshair across all panels.
    volume_profile: optional list of {price, buy_vol, sell_vol, total_vol}
    live_url: optional same-origin URL serving JSON {time,open,high,low,close,
        volume} for the latest bar. When set, JS polls and calls
        candleSeries.update() — no iframe rebuild, no zoom reset, no flicker.
        Caller must arrange for the file to be refreshed server-side (see
        analysis_tab._today_bar_writer / _intraday_bar_writer fragments).
    live_poll_ms: polling interval in ms. Use ~5000 for intraday, 30000 for
        daily — intraday bars change frequently so faster polling matches
        the WSS-driven live quote update rate.
                    for VP overlay on chart.
    """
    import json as _json

    # LWC requires strictly ascending times: one duplicate/out-of-order bar
    # kills the whole chart silently (blank panes, "Value is null" in console).
    # Weekly/monthly views survive because resample_ohlcv regroups; raw daily
    # must be sanitised here.
    if not df.empty and "time" in df.columns:
        df = df.sort_values("time").drop_duplicates(subset="time", keep="last")

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
    vwap_d, vwap_u1, vwap_l1, vwap_u2, vwap_l2 = [], [], [], [], []
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
        if (x := safe(row.get("vwap")))       is not None: vwap_d.append({"time":t,"value":x})
        if (x := safe(row.get("vwap_upper1"))) is not None: vwap_u1.append({"time":t,"value":x})
        if (x := safe(row.get("vwap_lower1"))) is not None: vwap_l1.append({"time":t,"value":x})
        if (x := safe(row.get("vwap_upper2"))) is not None: vwap_u2.append({"time":t,"value":x})
        if (x := safe(row.get("vwap_lower2"))) is not None: vwap_l2.append({"time":t,"value":x})
        # RSI/MACD: append whitespace ({time:t} without value) during warmup
        # period (NaN bars). Without this, the RSI/MACD chart panels have a
        # SHORTER time range than the price chart — when user pans left past
        # the RSI/MACD first valid bar, LWC constrains those panels' range,
        # and the constrained range gets propagated back via _flushSync,
        # snapping all 4 panels to the right edge.
        x = safe(row.get("rsi"))
        rsi_d.append({"time":t,"value":x} if x is not None else {"time":t})
        x = safe(row.get("macd"))
        macd_l.append({"time":t,"value":x} if x is not None else {"time":t})
        x = safe(row.get("macd_signal"))
        macd_s.append({"time":t,"value":x} if x is not None else {"time":t})
        x = safe(row.get("macd_hist"))
        if x is not None:
            macd_h.append({"time":t,"value":x,"color":"rgba(16,185,129,0.8)" if x>=0 else "rgba(239,68,68,0.8)"})
        else:
            macd_h.append({"time":t})

    if not candles:
        st.warning("Không có dữ liệu hợp lệ để vẽ chart.")
        return

    last_price = candles[-1]["close"]
    LWC_JS = __import__("pathlib").Path(__file__).parent / "lwc.min.js"
    try:
        lwc_code = LWC_JS.read_text(encoding="utf-8")
    except Exception:
        lwc_code = ""

    # VP overlay data for JS
    vp_js = "[]"
    if volume_profile:
        _vp_clean = []
        _max_vp_vol = max((float(r.get("total_vol", 0)) for r in volume_profile), default=1) or 1
        for r in volume_profile[:20]:
            _vp_clean.append({
                "p": round(float(r.get("price", 0)), 2),
                "b": round(float(r.get("buy_vol", 0)) / _max_vp_vol * 100, 1),
                "s": round(float(r.get("sell_vol", 0)) / _max_vp_vol * 100, 1),
            })
        vp_js = _json.dumps(_vp_clean)

    html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0e1a; font-family:monospace; color:#9ca3af; }
#wrapper { display:flex; flex-direction:column; height:100vh; padding:6px; gap:4px; }
.lbl { font-size:10px; color:#6b7280; text-transform:uppercase; padding:2px 4px; }
.ohlcv { font-size:11px; padding:1px 4px; min-height:16px; }
#mw { flex:5; display:flex; flex-direction:column; min-height:0; position:relative; }
#vw { flex:1.5; display:flex; flex-direction:column; min-height:0; }
#rw { flex:1.5; display:flex; flex-direction:column; min-height:0; }
#dw { flex:1.5; display:flex; flex-direction:column; min-height:0; }
#mc,#vc,#rc,#dc { flex:1; min-height:0; }
#vp-overlay { position:absolute; top:0; right:55px; bottom:0; width:100px;
  pointer-events:none; z-index:5; opacity:0.5; }
</style>
<script>""" + lwc_code + """</script>
</head>
<body>
<div id="wrapper">
  <div id="mw">
    <div class="lbl">""" + ticker + """ · Candlestick · EMA · BB</div>
    <div class="ohlcv" id="ohlcv">O — H — L — C —</div>
    <div id="mc"></div>
    <div id="vp-overlay"></div>
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
var VW=""" + _json.dumps(vwap_d) + """;
var VU1=""" + _json.dumps(vwap_u1) + """;
var VL1=""" + _json.dumps(vwap_l1) + """;
var VU2=""" + _json.dumps(vwap_u2) + """;
var VL2=""" + _json.dumps(vwap_l2) + """;
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
  // Fixed minimumWidth on the right price scale so all panels reserve the
  // same gutter for axis labels — keeps candle/volume/RSI/MACD chart areas
  // perfectly column-aligned regardless of the value range each shows.
  rightPriceScale:{borderColor:"#1f2937",minimumWidth:60},
  timeScale:{borderColor:"#1f2937",timeVisible:true,secondsVisible:false,rightOffset:5,shiftVisibleRangeOnNewBar:false},
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
var _livePriceLine = cs.createPriceLine({price:LP,color:"#fbbf24",lineWidth:1,
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
line(main,VW,"#e879f9",2,"VWAP");
line(main,VU1,"rgba(232,121,249,0.3)",1,"",false);
line(main,VL1,"rgba(232,121,249,0.3)",1,"",false);
line(main,VU2,"rgba(232,121,249,0.15)",1,"",false);
line(main,VL2,"rgba(232,121,249,0.15)",1,"",false);

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

var _isIntraday = false;
if (C.length >= 2) {
  _isIntraday = (C[C.length-1].time - C[C.length-2].time) < 86400;
}

// Crosshair sync — all panels mirror the same timestamp.
charts.forEach(function(s){
  s.subscribeCrosshairMove(function(p){
    if(!p.time) return;
    charts.forEach(function(t){
      if(t!==s) t.setCrosshairPosition(NaN,p.time,null);
    });
  });
});

// 4-panel time-scale sync — MUST use LOGICAL range, NOT time range.
//
// WHY logical range (bar indices), not time range (timestamps):
//   setVisibleRange({to: lastBarTime}) makes LWC think the chart is at
//   "live position" and triggers a right-edge snap that locks all panels
//   to the rightmost bar whenever the user pans right. Logical range
//   uses floating-point bar indices (0 … N-1+rightOffset) — LWC never
//   interprets these as a time boundary, so no snap occurs.
//   This invariant holds because all 4 charts have IDENTICAL bar counts:
//   RSI/MACD warmup bars use whitespace data {time:t} (no value), so the
//   indices are 1:1 across price / volume / RSI / MACD panels.
//
// DO NOT switch back to setVisibleRange / getVisibleRange / subscribeVisibleTimeRangeChange.
//
// Rule: NEVER call setVisibleLogicalRange from inside subscribeVisibleLogicalRangeChange
// on the same chart — corrupts LWC pan state (drag → zoom).
// _ready gate: ignore all callbacks until the initial setVisibleLogicalRange has
// run at T=200ms. This prevents RSI/MACD auto-fit (bar 14+) from being
// propagated to the price chart before we set the uniform initial range.
var _ready = false;
var _syncing = false;
var _pendingSrc = null;
charts.forEach(function(s){
  s.timeScale().subscribeVisibleLogicalRangeChange(function(){
    if (!_ready || _syncing) return;
    _pendingSrc = s;
  });
});
function _flushSync(){
  if (!_pendingSrc) return;
  var src = _pendingSrc;
  _pendingSrc = null;
  var r = src.timeScale().getVisibleLogicalRange();
  if (!r) return;
  _syncing = true;
  charts.forEach(function(c){
    if (c !== src) { try{c.timeScale().setVisibleLogicalRange(r);}catch(e){} }
  });
  _syncing = false;
}

// Volume Profile overlay
var VP=""" + vp_js + """;
function drawVP(){
  var ov=document.getElementById("vp-overlay");
  if(!ov||!VP.length) return;
  ov.innerHTML="";
  var ps=main.priceScale("right");
  var mc=document.getElementById("mc");
  if(!mc) return;
  var ch=mc.clientHeight;
  VP.forEach(function(v){
    var y=main.priceToCoordinate(v.p);
    if(y===null||y<0||y>ch) return;
    var bar=document.createElement("div");
    bar.style.cssText="position:absolute;right:0;height:3px;display:flex;top:"+Math.round(y)+"px";
    var bw=Math.max(1,v.b);
    var sw=Math.max(1,v.s);
    bar.innerHTML='<div style="width:'+bw+'px;height:100%;background:#10b981"></div>'+
      '<div style="width:'+sw+'px;height:100%;background:#ef4444"></div>';
    ov.appendChild(bar);
  });
}
if(VP.length){
  main.timeScale().subscribeVisibleLogicalRangeChange(drawVP);
  setTimeout(drawVP,200);
}

function resize(){
  var ids=["mc","vc","rc","dc"];
  [main,vol,rsi,mac].forEach(function(c,i){
    var el=document.getElementById(ids[i]);
    c.resize(el.clientWidth,el.clientHeight);
  });
  if(VP.length) setTimeout(drawVP,50);
}
window.addEventListener("resize",resize);
setTimeout(resize,100);
// Initial visible range + start sync machinery AFTER range is applied.
// Delay to 200ms (after the 100ms resize pass) so all panels have rendered.
// _ready is set to true only here — subscribeVisibleLogicalRangeChange callbacks
// are ignored before this point, so RSI/MACD auto-fit can't pollute the range.
setTimeout(function(){
  var N = C.length;
  if (N < 2) { _ready = true; return; }
  var r;
  if (!_isIntraday && N > 250) {
    r = {from: N-120, to: N-1};
  } else if (N > 375) {
    r = {from: N-375, to: N-1};
  } else {
    r = {from: 0, to: N-1};
  }
  _syncing = true;
  charts.forEach(function(c){ c.timeScale().setVisibleLogicalRange(r); });
  _syncing = false;
  _ready = true;
  // Start sync interval NOW — after the initial range is locked in.
  // Timer callbacks run outside LWC's event stack so setVisibleRange is safe.
  setInterval(_flushSync, 100);
  document.addEventListener("mouseup", function(){ setTimeout(_flushSync, 50); });
  document.addEventListener("touchend", function(){ setTimeout(_flushSync, 50); });
  var _wheelTimer = null;
  document.addEventListener("wheel", function(){
    if (_wheelTimer) clearTimeout(_wheelTimer);
    _wheelTimer = setTimeout(_flushSync, 150);
  }, {passive: true, capture: true});
}, 200);

// Prevent scroll/wheel from bubbling to parent Streamlit iframe
// This stops the page from jumping when scrolling/zooming on charts
document.body.style.overflow="hidden";
document.documentElement.style.overflow="hidden";

// ── Live last-bar polling ───────────────────────────────────────────────
// Smooth real-time update for today's candle WITHOUT rebuilding the iframe.
// Server writes today's OHLCV to a JSON file on a fragment timer; this JS
// fetches it and calls cs.update() — LWC redraws only the last bar so user's
// pan/zoom is preserved (unlike a Streamlit fragment-based chart rebuild).
var LIVE_URL=""" + _json.dumps(live_url or "") + """;
var LIVE_POLL_MS=""" + str(int(live_poll_ms)) + """;
if (LIVE_URL) {
  // Volume bar update is skipped — the original addHistogramSeries call wasn't
  // captured into a var, and updating just price keeps the visible "ticking"
  // behaviour users care about. Volume catches up on next page render.
  function _pollLastBar() {
    fetch(LIVE_URL + "?_=" + Date.now(), {cache: "no-store"})
      .then(function(r){
        if (!r.ok) { console.log("[live] HTTP " + r.status + " — today_bar file not ready"); return null; }
        return r.json();
      })
      .then(function(b){
        if (!b || typeof b.time !== "number") { console.log("[live] bad payload", b); return; }
        var lastT = C.length ? C[C.length-1].time : 0;
        console.log("[live] bar", b, "lastT", lastT, new Date(b.time*1000).toISOString());
        if (b.time < lastT) { console.log("[live] SKIP: b.time < lastT"); return; }
        cs.update({time:b.time, open:b.open, high:b.high, low:b.low, close:b.close});
        if (_livePriceLine) _livePriceLine.applyOptions({price: b.close});
        document.getElementById("ohlcv").innerHTML =
          "O <b style='color:#e5e7eb'>"+b.open.toFixed(2)+"</b>  "+
          "H <b style='color:#10b981'>"+b.high.toFixed(2)+"</b>  "+
          "L <b style='color:#ef4444'>"+b.low.toFixed(2)+"</b>  "+
          "C <b style='color:#fbbf24'>"+b.close.toFixed(2)+"</b>  "+
          "<span style='color:#6b7280;font-size:10px'>· LIVE</span>";
      })
      .catch(function(e){ console.log("[live] fetch error", e); });
  }
  _pollLastBar();              // immediate
  setInterval(_pollLastBar, LIVE_POLL_MS);
}
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


def fmt_pct(v) -> str:
    if v is None: return "—"
    return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"



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

@st.cache_data(ttl=600, show_spinner=False)
def load_watchlist() -> list:
    if not WATCHLIST_PATH.exists():
        return []
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            return json.load(f).get("tickers", [])
    except (OSError, PermissionError) as e:
        log.warning("Không đọc được watchlist (%s): %s", WATCHLIST_PATH, e)
    except json.JSONDecodeError as e:
        log.error("Watchlist JSON hỏng (%s): %s", WATCHLIST_PATH, e)
    return []


def save_watchlist(tickers: list):
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump({"tickers": sorted(set(tickers)), "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    # Invalidate cache so next load_watchlist() reads updated file
    load_watchlist.clear()


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
            except (ValueError, TypeError): return "#6b7280"
        if col == "RSI":
            try:
                v = float(val)
                if v<30: return "#10b981"
                if v>70: return "#ef4444"
                if v<40: return "#6ee7b7"
                if v>60: return "#fca5a5"
                return "#e5e7eb"
            except (ValueError, TypeError): return "#6b7280"
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
            except (ValueError, TypeError): return "400"
        if col == "RSI":
            try: return "700" if (float(val)<30 or float(val)>70) else "400"
            except (ValueError, TypeError): return "400"
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





_MARKET_OVERVIEW_PATH = Path("data_warehouse/_meta/market_overview.json")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_all_market_data() -> tuple:
    """
    Unified loader: 1 loop duy nhất cho cả market_overview + breadth.
    Returns: (sector_df, breadth_dict, ticker_display_df)

    Ưu tiên đọc market_overview.json (pre-computed bởi runner).
    Fallback: tính trực tiếp từ warehouse parquet (chậm ~10-30s).
    """
    # Tầng 1: file pre-computed bởi runner (instant load)
    if _MARKET_OVERVIEW_PATH.exists():
        try:
            age_hours = (datetime.now().timestamp() - _MARKET_OVERVIEW_PATH.stat().st_mtime) / 3600
            if age_hours < 24:
                data = json.loads(_MARKET_OVERVIEW_PATH.read_text(encoding="utf-8"))
                sector_df = pd.DataFrame(data["sectors"])
                breadth = data["breadth"]
                tick_df = pd.DataFrame(data["tickers"])
                log.info("Market data: loaded from pre-computed file (%.1fh old)", age_hours)
                return sector_df, breadth, tick_df
        except (OSError, json.JSONDecodeError, KeyError) as e:
            log.warning("Market overview file corrupt: %s", e)

    # Tầng 2: tính trực tiếp (fallback, chậm)
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

        # Freefloat lookup (optional — falls back to 30% proxy if file absent)
        _freefloat_map: dict = {}
        try:
            from vnstock_freefloat import FreefloatUpdater
            _freefloat_map = FreefloatUpdater("data_warehouse").load_map()
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

                # Normalize mixed price units (VND vs nghìn VND)
                df = _normalize_price_units(df)

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
                vol5_sum  = float(v90.tail(5).sum())
                vol10_sum = float(v90.tail(10).sum())
                vol20_sum = float(v90.tail(20).sum())

                amp  = (h90 - l90) / c90 * 100
                amp5  = float(amp.tail(5).mean())
                amp20 = float(amp.tail(20).mean())
                amp60 = float(amp.tail(60).mean()) if len(amp) >= 60 else amp5

                # Giá đã normalize ở trên → c90 cũng đã normalize
                chg5  = float((c90.iloc[-1]/c90.iloc[-6]-1)*100)  if len(c90)>5  else None
                chg20 = float((c90.iloc[-1]/c90.iloc[-21]-1)*100) if len(c90)>20 else None
                chg60 = float((c90.iloc[-1]/c90.iloc[-61]-1)*100) if len(c90)>60 else None

                # Safety clamp
                if chg5 is not None and abs(chg5) > 50:
                    chg5 = None
                if chg20 is not None and abs(chg20) > 80:
                    chg20 = None
                if chg60 is not None and abs(chg60) > 150:
                    chg60 = None

                issue_share = shares_map.get(ticker, 0)

                # Giá đã normalize ở trên → last luôn ở nghìn VND
                # mktcap = giá (nghìn VND) × 1000 (→ VND) × shares / 1e9 (→ tỷ)
                mktcap = last * 1000 * issue_share / 1e9 if issue_share > 0 else 0.0
                mktcap_proxy = last * 1000 * vol20 / 1e9
                _ff_pct = _freefloat_map.get(ticker, 30.0)
                freefloat_val = round(mktcap * _ff_pct / 100, 1)
                freefloat_shares = issue_share * _ff_pct / 100

                rows.append({
                    "ticker": ticker, "last": last,
                    "vol5": vol5, "vol10": vol10, "vol20": vol20,
                    "vol5_sum": vol5_sum, "vol10_sum": vol10_sum, "vol20_sum": vol20_sum,
                    "mktcap": mktcap, "mktcap_proxy": mktcap_proxy,
                    "freefloat_val": freefloat_val, "freefloat_shares": freefloat_shares,
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

        # ── Foreign flow từ TopStock API (isolated so failure doesn't block table)
        _nn_w, _nn_m, _nn_3m = {}, {}, {}
        try:
            _nn_raw_mkt = _fetch_foreign_net_flow(trading_days=20, limit=100)
            _nn_w  = _aggregate_nn_by_window(_nn_raw_mkt, 7)    # 1 tuần
            _nn_m  = _aggregate_nn_by_window(_nn_raw_mkt, 30)   # 1 tháng
            _nn_3m = _aggregate_nn_by_window(_nn_raw_mkt, 90)   # 3 tháng
        except Exception as e:
            log.warning("NN flow fetch failed (non-blocking): %s", e)

        # ── Aggregate theo ngành ──────────────────────────────────────────────
        def agg(grp):
            n = len(grp)
            v20 = grp["vol20"].sum()
            v5  = grp["vol5"].sum()
            v10 = grp["vol10"].sum()
            total_mktcap = grp["mktcap"].sum()
            gtgd_tb = grp["mktcap_proxy"].sum()

            vs   = grp["vol5_sum"].sum()
            vs10 = grp["vol10_sum"].sum()
            vs20 = grp["vol20_sum"].sum()
            ff_sh = grp["freefloat_shares"].sum()
            vol5_20  = round(vs / vs20 * 100, 0) if vs20 > 0 else None
            avg5_10  = round((v5 / v10 - 1) * 100, 1) if v10 > 0 else None
            avg10_20 = round((v10 / v20 - 1) * 100, 1) if v20 > 0 else None
            vol5_free  = round(vs  / ff_sh * 100, 2) if ff_sh > 0 else None
            vol10_free = round(vs10 / ff_sh * 100, 2) if ff_sh > 0 else None
            vol20_free = round(vs20 / ff_sh * 100, 2) if ff_sh > 0 else None

            # Foreign flow (tỷ VND, đã aggregate bởi _aggregate_nn_by_window)
            tickers_in = grp["ticker"].tolist()
            net_w  = sum(_nn_w.get(t, 0)  for t in tickers_in)
            net_m  = sum(_nn_m.get(t, 0)  for t in tickers_in)
            net_3m = sum(_nn_3m.get(t, 0) for t in tickers_in)

            total_freefloat = grp["freefloat_val"].sum()
            return pd.Series({
                "Số mã":          n,
                "Vốn hoá (tỷ)":   round(total_mktcap, 0),
                "Freefloat (tỷ)": round(total_freefloat, 0),
                "GTGD TB (tỷ)":   round(gtgd_tb, 0),
                "Vol Avg 5":    round(v5  / 1e6, 1),
                "Vol Avg 10":   round(v10 / 1e6, 1),
                "Vol Avg 20":   round(v20 / 1e6, 1),
                "AVG 5-10 %":   avg5_10,
                "AVG 10-20 %":  avg10_20,
                "Vol 5/Free %": vol5_free,
                "Vol 10/Free %": vol10_free,
                "Vol 20/Free %": vol20_free,
                "Vol 5/20 %":   vol5_20,
                "Biên 1T (%)":  round(grp["amp5"].mean(),  1),
                "Biên 1M (%)":  round(grp["amp20"].mean(), 1),
                "Biên 3M (%)":  round(grp["amp60"].mean(), 1),
                "Giá 1T %":     round(grp["chg5"].dropna().mean(),  1) if grp["chg5"].notna().any()  else None,
                "Giá 1M %":     round(grp["chg20"].dropna().mean(), 1) if grp["chg20"].notna().any() else None,
                "Giá 3M %":     round(grp["chg60"].dropna().mean(), 1) if grp["chg60"].notna().any() else None,
                "NN 1T (tỷ)":   round(net_w,  1) if net_w  != 0 else None,
                "NN 1M (tỷ)":   round(net_m,  1) if net_m  != 0 else None,
                "NN 3M (tỷ)":   round(net_3m, 1) if net_3m != 0 else None,
            })

        # Ticker-level display data
        tick_display = merged.copy()
        tick_display["Vốn hoá (tỷ)"] = tick_display["mktcap"].round(0)
        tick_display["Freefloat (tỷ)"] = tick_display["freefloat_val"].round(0)
        tick_display["GTGD TB (tỷ)"] = tick_display["mktcap_proxy"].round(1)
        tick_display["Vol Avg 5"] = (tick_display["vol5"] / 1e6).round(1)
        tick_display["Vol Avg 10"] = (tick_display["vol10"] / 1e6).round(1)
        tick_display["Vol Avg 20"] = (tick_display["vol20"] / 1e6).round(1)
        tick_display["AVG 5-10 %"] = np.where(
            tick_display["vol10"] > 0,
            ((tick_display["vol5"] / tick_display["vol10"] - 1) * 100).round(1), None)
        tick_display["AVG 10-20 %"] = np.where(
            tick_display["vol20"] > 0,
            ((tick_display["vol10"] / tick_display["vol20"] - 1) * 100).round(1), None)
        tick_display["Vol 5/Free %"] = np.where(
            tick_display["freefloat_shares"] > 0,
            (tick_display["vol5_sum"] / tick_display["freefloat_shares"] * 100).round(2), None)
        tick_display["Vol 10/Free %"] = np.where(
            tick_display["freefloat_shares"] > 0,
            (tick_display["vol10_sum"] / tick_display["freefloat_shares"] * 100).round(2), None)
        tick_display["Vol 20/Free %"] = np.where(
            tick_display["freefloat_shares"] > 0,
            (tick_display["vol20_sum"] / tick_display["freefloat_shares"] * 100).round(2), None)
        tick_display["Vol 5/20 %"] = np.where(
            tick_display["vol20_sum"] > 0,
            (tick_display["vol5_sum"] / tick_display["vol20_sum"] * 100).round(0),
            None
        )
        tick_display["Biên 1T (%)"] = tick_display["amp5"].round(1)
        tick_display["Biên 1M (%)"] = tick_display["amp20"].round(1)
        tick_display["Biên 3M (%)"] = tick_display["amp60"].round(1)
        tick_display["Giá 1T %"] = tick_display["chg5"].round(1)
        tick_display["Giá 1M %"] = tick_display["chg20"].round(1)
        tick_display["Giá 3M %"] = tick_display["chg60"].round(1)
        # NN từ TopStock (đã fetch ở trên) — map per-ticker
        tick_display["NN 1T (tỷ)"] = tick_display["ticker"].map(_nn_w)
        tick_display["NN 1M (tỷ)"] = tick_display["ticker"].map(_nn_m)
        tick_display["NN 3M (tỷ)"] = tick_display["ticker"].map(_nn_3m)
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




@st.cache_data(ttl=3600, show_spinner=False)
def load_index_overview(days: int = 90) -> pd.DataFrame:
    """
    Lấy dữ liệu chỉ số VNINDEX, VN30, HNXINDEX, HNX30 từ API.
    Trả về DataFrame pivot: mỗi dòng = 1 ngày, cột = index metrics.
    """
    try:
        from vnstock_auth import get_vnstock
        from datetime import date, timedelta

        start = (date.today() - timedelta(days=days + 15)).strftime("%Y-%m-%d")
        end = date.today().strftime("%Y-%m-%d")
        indices = ["VNINDEX", "VN30", "HNXINDEX", "HNX30"]

        def _fetch_idx(idx_name):
            try:
                stock = get_vnstock(idx_name)
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
    if st.button(
        "🔄 Refresh",
        key="top_refresh",
        width='stretch',
        help=(
            "**Vẽ lại dashboard** (nhanh, ~1 giây).\n\n"
            "Xoá cache RAM rồi đọc lại file `vnstock_data.json` hiện có — "
            "KHÔNG tính lại screener, KHÔNG tải giá mới.\n\n"
            "**Dùng khi:** đổi filter/theme/watchlist, hoặc UI có vẻ stale.\n\n"
            "Ẩn dụ: *lật lại trang báo cũ*."
        ),
    ):
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
except (ValueError, TypeError, IndexError):
    pass

_info_col, _update_col = st.columns([5, 3])
with _info_col:
    if _screener_stale:
        st.markdown(f'<p class="updated-at" style="color:#f59e0b">⚠️ Screener cũ: {gen_time} — Bấm "Cập nhật Screener" để refresh</p>', unsafe_allow_html=True)
    else:
        st.markdown(f'<p class="updated-at">Cập nhật lúc: {gen_time}</p>', unsafe_allow_html=True)
with _update_col:
    _uc1, _uc2, _uc3 = st.columns(3)
    with _uc1:
        if st.button(
            "📥 Cập nhật giá",
            key="run_updater",
            use_container_width=True,
            help=(
                "**Tải giá mới nhất từ API + tính lại screener** "
                "(8 luồng song song + bỏ mã đã hủy niêm yết; VCI ốm → tự "
                "fallback KBS có đối chiếu giá).\n\n"
                "Mở cửa sổ PowerShell riêng chạy `vnstock_updater.py --force "
                "--workers 8 --skip-stale-days 90` → ghi đè parquet trong "
                "`data_warehouse/prices/` → `vnstock_runner.py` tạo lại "
                "`vnstock_data.json` (screener đi kèm giá — giá mới mà "
                "overview cũ là brief cảnh báo phiên cũ).\n\n"
                "Tin tức/vĩ mô KHÔNG nằm ở đây nữa — đó là việc của nút "
                "**🧩 Cập nhật còn lại** (tránh chạy trùng).\n\n"
                "Nếu API báo rate-limit, giảm `--workers` (vd 4).\n\n"
                "**Dùng khi:** muốn xem data ngày mới nhất (sau giờ giao dịch).\n\n"
                "Sau khi PowerShell xong, bấm **Refresh** hoặc F5 "
                "để dashboard đọc dữ liệu mới.\n\n"
                "Ẩn dụ: *tổ chức thêm trận đấu + in tờ báo mới*."
            ),
        ):
            _is_win, _log = launch_in_new_console(
                commands=[
                    {"label": "Cap nhat gia",     "args": ["vnstock_updater.py", "--force",
                                                           "--workers", "8", "--skip-stale-days", "90"]},
                    {"label": "Refresh Screener", "args": ["vnstock_runner.py"]},
                ],
                log_filename="updater.log",
            )
            if _is_win:
                st.success(
                    "✅ Đã mở cửa sổ PowerShell chạy updater + screener.\n\n"
                    "Theo dõi tiến độ trong cửa sổ mới. Khi xong, bấm **Refresh** "
                    "hoặc F5 để dashboard load dữ liệu mới."
                )
            else:
                st.info(
                    f"🔄 Updater đang chạy nền. Log: `{_log}`\n\n"
                    "Khi xong, bấm **Refresh** để load dữ liệu mới."
                )
    with _uc2:
        if st.button(
            "🧩 Cập nhật còn lại",
            key="run_all_no_sync",
            use_container_width=True,
            help=(
                "**Chạy pipeline `run.py all --no-sync`** — toàn bộ 13 bước "
                "TRỪ kho giá parquet ~1.724 mã (~10-25 phút thay vì 35-55):\n"
                "- Screener + market_overview (nguồn của brief/breadth/dòng "
                "tiền ngành)\n"
                "- Tin tức + sentiment\n"
                "- NN ròng full-market (foreign-flow)\n"
                "- Vĩ mô 13 chỉ số (FX/LNH ngày/HNX/FRED/NSO/policy)\n"
                "- Gold, allocation band, scorecard\n"
                "- Test badge, audit/reconcile rec\n"
                "- **Train chiến lược** (`vnstock_train --once`: tune/revise + "
                "gate validation 🧪 + decay — phần tốn thời gian nhất, backtest "
                "VN30 ~5-15 phút)\n"
                "- Reflection, doctor badge\n\n"
                "**Dùng khi:** kho giá đã tươi (vừa bấm 📥 Cập nhật giá / "
                "pipeline đêm đã sync) mà muốn làm mới mọi thứ CÒN LẠI; hoặc "
                "VCI outage không tải được giá nhưng vẫn muốn tin/vĩ mô/band "
                "mới nhất.\n\n"
                "Ẩn dụ: *toà soạn làm mọi việc trừ đi lấy bảng giá*."
            ),
        ):
            _is_win, _log = launch_in_new_console(
                commands=[
                    {"label": "Cap nhat con lai (all --no-sync)",
                     "args": ["run.py", "all", "--no-sync"]},
                ],
                log_filename="pipeline_rest.log",
            )
            if _is_win:
                st.success(
                    "✅ Đã mở cửa sổ PowerShell chạy phần còn lại của pipeline "
                    "(~10-25 phút, không đụng kho giá — gồm cả train chiến lược).\n\n"
                    "Khi xong, bấm **Refresh** hoặc F5 để dashboard load dữ liệu mới."
                )
            else:
                st.info(
                    f"🔄 Pipeline (không sync giá) đang chạy nền. Log: `{_log}`\n\n"
                    "Khi xong, bấm **Refresh** để load dữ liệu mới."
                )
    with _uc3:
        if st.button(
            "🚀 Cập nhật tất cả",
            key="run_all_pipeline",
            use_container_width=True,
            help=(
                "**Chạy TRỌN pipeline tối `python run.py all` — 13 bước** "
                "(~35-55 phút): sync giá → validate → screener → news → "
                "foreign-flow → **vĩ mô 13 chỉ số** → gold → allocation → "
                "test → audit/reconcile → **train chiến lược** → reflection "
                "→ doctor.\n\n"
                "Đúng thứ Task Scheduler chạy 18:00 mỗi tối — dùng nút này khi "
                "muốn làm tươi TOÀN BỘ (kho giá + overview + tin + NN ròng + "
                "vĩ mô + band phân bổ + 2 badge sidebar) trong một phát, vd "
                "khi task đêm bị lỡ.\n\n"
                "⚠️ **ĐỪNG tắt máy / đóng cửa sổ PowerShell khi đang chạy** — "
                "chuỗi bị ngắt giữa chừng là cache tươi nửa vời (đúng bệnh "
                "LastTaskResult 0xC000013A của task đêm).\n\n"
                "Khác biệt: **📥 Cập nhật giá** chỉ lo giá + screener; nút này "
                "chạy đủ 13 bước kể cả allocation/audit/train/doctor.\n\n"
                "Xong thì bấm **🔄 Refresh** hoặc F5.\n\n"
                "Ẩn dụ: *tự tay chạy nguyên ca trực đêm của toà soạn*."
            ),
        ):
            _is_win, _log = launch_in_new_console(
                commands=[
                    {"label": "Pipeline run.py all (13 buoc)",
                     "args": ["run.py", "all"]},
                ],
                log_filename="pipeline_all.log",
            )
            if _is_win:
                st.success(
                    "✅ Đã mở cửa sổ PowerShell chạy TRỌN pipeline (~35-55 phút).\n\n"
                    "⚠️ Đừng tắt máy / đóng cửa sổ khi đang chạy. Theo dõi từng "
                    "bước `=== run.py all :: … ===` trong cửa sổ mới; xong thì "
                    "bấm **🔄 Refresh** hoặc F5."
                )
            else:
                st.info(
                    f"🔄 Pipeline đang chạy nền (~35-55 phút). Log: `{_log}`\n\n"
                    "Khi xong, bấm **🔄 Refresh** để load dữ liệu mới."
                )

total_tickers = data.get("total_tickers", 0)
classified    = data.get("classified_tickers", 0)
presets_data  = data.get("presets", {})
total_hits    = sum(v.get("count", 0) for v in presets_data.values())
top_preset    = max(presets_data.items(), key=lambda x: x[1].get("count", 0), default=("—", {}))
industry_summary = data.get("industry_summary", {})

# ── Theme toggle ──────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Test status badge ──────────────────────────────────────────────
    try:
        _ts_path = Path("data_warehouse/_meta/test_status.json")
        if _ts_path.exists():
            _ts = json.loads(_ts_path.read_text(encoding="utf-8"))
            _ts_ran = _ts.get("ran_at", "")
            _ts_passed = _ts.get("passed", 0)
            _ts_failed = _ts.get("failed", 0)
            _ts_errors = _ts.get("errors", 0)
            _ts_mode   = _ts.get("mode", "?")
            _ts_total_bad = _ts_failed + _ts_errors
            # Age
            try:
                _age_d = (datetime.now() - datetime.fromisoformat(_ts_ran)).days
                _age_str = f"{_age_d}d trước" if _age_d > 0 else "hôm nay"
            except Exception:
                _age_str = "?"
            _ts_color = "#22c55e" if _ts_total_bad == 0 else "#ef4444"
            _ts_icon  = "✅" if _ts_total_bad == 0 else "❌"
            st.markdown(
                f'<div style="padding:6px 10px;border-radius:6px;'
                f'border:1px solid {_ts_color};background:rgba(30,41,59,0.4);'
                f'font-size:11px;color:{_ts_color};margin-bottom:8px;'
                f'font-family:\'IBM Plex Sans\',sans-serif">'
                f'{_ts_icon} <b>Tests {_ts_mode}</b>: {_ts_passed} passed'
                + (f", <b>{_ts_total_bad} fail</b>" if _ts_total_bad else "")
                + f'<br><span style="color:#9ca3af">Chạy {_age_str} · {_ts.get("elapsed_s","?")}s</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="padding:6px 10px;border-radius:6px;'
                'border:1px solid #6b7280;background:rgba(30,41,59,0.4);'
                'font-size:11px;color:#9ca3af;margin-bottom:8px;'
                'font-family:\'IBM Plex Sans\',sans-serif">'
                '⏸ Tests chưa chạy.<br>'
                '<code>python run.py test --fast</code>'
                '</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # ── Doctor badge (sức khỏe nguồn dữ liệu — run.py doctor) ──────────
    try:
        _dr_path = Path("data_warehouse/_meta/doctor_status.json")
        if _dr_path.exists():
            _dr = json.loads(_dr_path.read_text(encoding="utf-8"))
            _dr_counts = _dr.get("counts", {})
            _dr_worst = _dr.get("worst", "ok")
            try:
                _dr_age_d = (datetime.now()
                             - datetime.fromisoformat(_dr.get("ran_at", ""))).days
                _dr_age = f"{_dr_age_d}d trước" if _dr_age_d > 0 else "hôm nay"
            except Exception:
                _dr_age = "?"
            _dr_color = {"ok": "#22c55e", "off": "#9ca3af",
                         "warn": "#eab308", "error": "#ef4444"}.get(_dr_worst, "#9ca3af")
            _dr_parts = " · ".join(
                f"{_dr_counts.get(_s, 0)}{_i}"
                for _s, _i in (("ok", "✅"), ("warn", "⚠️"), ("off", "⬜"), ("error", "❌"))
                if _dr_counts.get(_s, 0))
            st.markdown(
                f'<div style="padding:6px 10px;border-radius:6px;'
                f'border:1px solid {_dr_color};background:rgba(30,41,59,0.4);'
                f'font-size:11px;color:{_dr_color};margin-bottom:8px;'
                f'font-family:\'IBM Plex Sans\',sans-serif">'
                f'🩺 <b>Nguồn dữ liệu</b>: {_dr_parts or "?"}'
                f'<br><span style="color:#9ca3af">Khám {_dr_age} · {_dr.get("mode", "?")}'
                f' · <code>run.py doctor</code></span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    _theme = st.toggle("☀️ Light mode", value=False, key="light_mode")
    if _theme:
        _t = THEMES["light"]
        st.markdown(f"""<style>
        .stApp {{ background: {_t['bg']} !important; }}
        .metric-card {{ background: {_t['card_bg']} !important; border-color: {_t['border']} !important; }}
        .metric-card .value {{ color: {_t['text']} !important; }}
        .metric-card .label, .metric-card .sub {{ color: {_t['text3']} !important; }}
        .card {{ background: {_t['card_bg']} !important; border-color: {_t['border']} !important; }}
        .card-title {{ color: {_t['text2']} !important; }}
        .section-title {{ color: {_t['text2']} !important; }}
        [data-testid="stSidebar"] {{ background: {_t['card_bg']} !important; }}
        [data-testid="stMarkdownContainer"] p {{ color: {_t['text2']}; }}
        </style>""", unsafe_allow_html=True)

# All constants and functions are defined above this point.
# Refresh the sys.modules alias on every run so tab modules that do
# `from vnstock_dashboard import …` always see the current __main__ object
# (Streamlit creates a fresh __main__ on each hot-reload).
sys.modules["vnstock_dashboard"] = sys.modules["__main__"]

# ── NAVIGATION (dùng pills thay tabs để tránh lazy-render) ────────────────────
_TAB_OPTIONS = ["📊 Screener", "🔬 Phân tích", "🌏 Thị trường", "🗞️ Tin tức", "💰 Dòng Tiền", "💼 Portfolio", "⚕️ Sức khỏe"]
_active_tab = st.pills("", _TAB_OPTIONS, default="📊 Screener", key="nav_tab")

# ══════════════════════════════════════════════════════
# TAB 1: SCREENER
# ══════════════════════════════════════════════════════
if _active_tab == "📊 Screener":
    try:
        from dashboard.screener_tab import render_screener_tab
        render_screener_tab(
            presets_data=presets_data,
            industry_summary=industry_summary,
            gen_time=gen_time,
            total_tickers=total_tickers,
            classified=classified,
            total_hits=total_hits,
            top_preset=top_preset,
        )
    except Exception as _e:
        st.error(f"Không render được Screener tab: {_e}")
        st.caption("Kiểm tra `dashboard/screener_tab.py` và các preset JSON.")


# ══════════════════════════════════════════════════════
# TAB 2: PHÂN TÍCH
# ══════════════════════════════════════════════════════
if _active_tab == "🔬 Phân tích":
    try:
        from dashboard.analysis_tab import render_analysis_tab
        render_analysis_tab()
    except Exception as _e:
        st.error(f"Không render được Phân tích tab: {_e}")
        st.caption("Kiểm tra `dashboard/analysis_tab.py` và các cache trong `data_warehouse/`.")



# ══════════════════════════════════════════════════════
# TAB 3: THỊ TRƯỜNG
# ══════════════════════════════════════════════════════
if _active_tab == "🌏 Thị trường":
    try:
        from dashboard.market_tab import render_market_tab
        render_market_tab()
    except Exception as _e:
        st.error(f"Không render được Thị trường tab: {_e}")
        st.caption("Kiểm tra `dashboard/market_tab.py` và cache `data_warehouse/_meta/`.")




# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# TAB: DÒNG TIỀN (Money Flow)
# ══════════════════════════════════════════════════════════════════════════════
if _active_tab == "💰 Dòng Tiền":
    try:
        from dashboard.money_flow_tab import render_money_flow_tab
        render_money_flow_tab()
    except Exception as _e:
        st.error(f"Không render được Dòng Tiền tab: {_e}")
        st.caption("Kiểm tra `dashboard/money_flow_tab.py` và các cache trong `data_warehouse/_meta/`.")




# ══════════════════════════════════════════════════════════════════════════════
# TAB: Portfolio
# ══════════════════════════════════════════════════════════════════════════════

if _active_tab == "🗞️ Tin tức":
    try:
        from dashboard.news_tab import render_news_tab
        render_news_tab()
    except Exception as _e:
        st.error(f"Không render được Tin tức tab: {_e}")
        st.caption("Kiểm tra `dashboard/news_tab.py` và `vnstock_news.py`.")

if _active_tab == "💼 Portfolio":
    try:
        from dashboard.portfolio_tab import render_portfolio_tab
        render_portfolio_tab(Path("data_warehouse"))
    except Exception as _e:
        st.error(f"Không render được Portfolio tab: {_e}")
        st.caption("Kiểm tra `dashboard/portfolio_tab.py` và `data_warehouse/_meta/portfolio.json`.")


# ══════════════════════════════════════════════════════
# TAB 6: SYSTEM HEALTH (Feature 3C)
# ══════════════════════════════════════════════════════
if _active_tab == "⚕️ Sức khỏe":
    try:
        from vnstock_health import render_health_tab
        render_health_tab()
    except Exception as _e:
        st.error(f"Không render được Health tab: {_e}")
        st.caption("Kiểm tra `vnstock_health.py` và các file metadata trong `data_warehouse/_meta/`.")
