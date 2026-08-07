"""
vnstock_wss.py — Real-time WebSocket client cho VnStock Dashboard
===================================================================
Stream tick/quote real-time cho VN30 + các chỉ số chính (VNINDEX, VN30,
HNXINDEX, HNX30). Lưu trữ 3 tầng:

  Tầng 1 — Live quote snapshot (JSON, overwrite mỗi tick)
      data_warehouse/_live/quote_{TICKER}.json
  Tầng 2 — 1-minute OHLCV bars (Parquet, flush mỗi 60s)
      data_warehouse/_live/bars_{YYYY-MM-DD}.parquet
  Tầng 3 — Daily rollup → existing warehouse (manual/cron)

Usage:
    from vnstock_wss import get_wss_client
    client = get_wss_client()
    client.start()
    client.subscribe_all()
    # ... later
    client.stop()

Standalone test:
    python vnstock_wss.py --test       # smoke test 60s
    python vnstock_wss.py --status     # print status
"""
from __future__ import annotations

import json
import os
import sys
import time
import threading
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

from vnstock_auth import ensure_api_key, get_api_key

import pandas as pd

# ═════════════════════════════════════════════════════════════════════════════
# Constants
# ═════════════════════════════════════════════════════════════════════════════

VN30_SYMBOLS = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]

INDEX_SYMBOLS = ["VNINDEX", "VN30", "HNXINDEX", "HNX30"]

FUTURES_SYMBOLS = ["VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"]


def is_futures(ticker: str) -> bool:
    """
    Check nếu ticker là hợp đồng tương lai VN30.

    Nhận diện 3 format:
    - Friendly names: VN30F1M, VN30F2M, VN30F1Q, VN30F2Q
    - Expiry codes:   VN30F2410, VN30F2504 (YYMM)
    - HNX internal:   41I1G4000, 41I1G5000, ... (Market.price_board trả về)
    """
    t = str(ticker).upper()
    if t in FUTURES_SYMBOLS:
        return True
    if t.startswith("VN30F") and len(t) >= 6:
        return True
    # HNX internal futures code: 41I... (dẫn xuất chỉ số)
    if t.startswith("41I") and len(t) >= 6:
        return True
    return False


ALL_SYMBOLS = VN30_SYMBOLS + INDEX_SYMBOLS + FUTURES_SYMBOLS

# Cache danh sách toàn bộ mã niêm yết (refresh mỗi ngày)
_ALL_LISTED_CACHE: list[str] = []
_ALL_LISTED_DATE: str = ""


def get_all_listed_symbols() -> list[str]:
    """
    Lấy danh sách toàn bộ mã niêm yết HOSE + HNX + UPCOM.
    Cache theo ngày — chỉ gọi API 1 lần/ngày.
    Fallback về VN30_SYMBOLS nếu API fail.
    """
    global _ALL_LISTED_CACHE, _ALL_LISTED_DATE
    from datetime import date
    today = date.today().isoformat()

    if _ALL_LISTED_DATE == today and _ALL_LISTED_CACHE:
        return _ALL_LISTED_CACHE

    symbols = []
    try:
        from vnstock_data import Reference
        ensure_api_key()
        ref = Reference()
        for exchange in ("HOSE", "HNX", "UPCOM"):
            try:
                df = ref.equity.list(exchange=exchange)
                if df is not None and not df.empty:
                    # Tìm cột ticker/symbol
                    col = None
                    for c in df.columns:
                        if str(c).lower() in ("ticker", "symbol", "code",
                                               "stocksymbol", "stock_symbol"):
                            col = c
                            break
                    if col is None and len(df.columns) > 0:
                        col = df.columns[0]
                    if col:
                        syms = df[col].dropna().astype(str).str.upper().tolist()
                        symbols.extend(syms)
            except Exception:
                continue
    except ImportError:
        pass

    if not symbols:
        # Fallback: scan warehouse ticker folders
        try:
            from pathlib import Path
            prices_dir = Path("data_warehouse/prices")
            if prices_dir.exists():
                symbols = sorted([
                    p.name.replace("ticker=", "")
                    for p in prices_dir.iterdir()
                    if p.is_dir() and p.name.startswith("ticker=")
                ])
        except Exception:
            pass

    if symbols:
        # Dedup + filter invalid
        seen = set()
        clean = []
        for s in symbols:
            s = s.strip().upper()
            if s and len(s) <= 10 and s not in seen and not is_futures(s):
                seen.add(s)
                clean.append(s)
        _ALL_LISTED_CACHE = sorted(clean)
        _ALL_LISTED_DATE = today
        print(f"[vnstock_wss] Listed symbols: {len(_ALL_LISTED_CACHE)} "
              f"(HOSE+HNX+UPCOM)")
    else:
        _ALL_LISTED_CACHE = list(VN30_SYMBOLS)
        print("[vnstock_wss] Fallback to VN30 only")

    return _ALL_LISTED_CACHE


# ═════════════════════════════════════════════════════════════════════════════
# Depth parser — parse multi-level bid/ask từ price_board row
# ═════════════════════════════════════════════════════════════════════════════

def _pick_depth_levels(row, columns: list, side: str,
                       max_levels: int = 10) -> list[dict]:
    """
    Parse bid/ask levels từ 1 row của price_board DataFrame.
    side = 'bid' | 'ask'. Returns list of {"price", "volume"} từ best → kém.
    Flexible column naming: bestbid1/bestbidvol1, bid_price_1/bid_vol_1, v.v.
    Dừng khi gặp level không có price.
    """
    if side == "bid":
        price_patterns = ["bestbid{i}", "best_bid_{i}", "bidprice{i}",
                          "bid_price_{i}", "bid{i}price", "bid{i}"]
        vol_patterns = ["bestbidvol{i}", "bestbidvolume{i}", "best_bid_vol_{i}",
                        "bidvol{i}", "bid_vol_{i}", "bidvolume{i}", "bid{i}vol",
                        "bid{i}volume"]
    else:
        price_patterns = ["bestoffer{i}", "best_offer_{i}", "bestask{i}",
                          "best_ask_{i}", "askprice{i}", "ask_price_{i}",
                          "offerprice{i}", "ask{i}", "offer{i}"]
        vol_patterns = ["bestoffervol{i}", "bestoffervolume{i}",
                        "best_offer_vol_{i}", "bestaskvol{i}", "askvol{i}",
                        "ask_vol_{i}", "offervol{i}", "ask{i}vol",
                        "ask{i}volume", "offer{i}vol"]

    def _find(key: str):
        for col in columns:
            if key in col:
                try:
                    v = row[col]
                    if v is not None and not pd.isna(v):
                        fv = float(v)
                        return fv
                except Exception:
                    continue
        return None

    levels: list[dict] = []
    for i in range(1, max_levels + 1):
        price = None
        for pat in price_patterns:
            price = _find(pat.format(i=i))
            if price is not None and price > 0:
                break
        if price is None or price <= 0:
            break
        volume = None
        for pat in vol_patterns:
            volume = _find(pat.format(i=i))
            if volume is not None:
                break
        levels.append({"price": price, "volume": volume or 0})
    return levels


LIVE_DIR = Path("data_warehouse/_live")
LIVE_DIR.mkdir(parents=True, exist_ok=True)

STATUS_PATH = LIVE_DIR / "status.json"

# HOSE trading hours (Asia/Ho_Chi_Minh, UTC+7)
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 0)

# Bar flush interval (seconds)
BAR_FLUSH_INTERVAL = 60

# Sanity threshold: any single tick contributing >MAX_SINGLE_TICK_VOLUME
# shares to a 1-minute bar is almost certainly a bug. The most-traded VN
# tickers do ~5M-20M shares/day spread across 250 trading minutes ≈ 20-80K
# per minute. A 500K-share single-tick event would mean a single block
# trade of >5x the typical bar's worth of activity. Plausible? Maybe at
# very rare ATC prints, but worth flagging.
#
# Real-world bug seen on the user's warehouse: AAA rolled_volume came in at
# 113M for a day where the API showed 1.4M (78×). Root cause: somewhere
# in the tick path `accum_volume` (cumulative session total) was used in
# place of `_delta_volume`, and each tick added the full running total to
# the current bar — exponential blowup.
MAX_SINGLE_TICK_VOLUME = 500_000


# ═════════════════════════════════════════════════════════════════════════════
# BarAggregator — aggregate ticks → 1m OHLCV bars in-memory
# ═════════════════════════════════════════════════════════════════════════════

def accum_to_delta(
    last_accum: Optional[float],
    last_date: Optional[str],
    accum: float,
    today: str,
) -> float:
    """
    Convert session-accumulated volume to per-tick delta for bar aggregation.

    Returns 0.0 as a safety baseline when:
      - no prior state for this ticker (first tick or restart)
      - a new trading day has begun
      - accum went backwards (session reset)
    Otherwise returns (accum - last_accum).
    """
    if last_date != today or last_accum is None or accum < last_accum:
        return 0.0
    return max(0.0, float(accum) - float(last_accum))


class BarAggregator:
    """
    In-memory 1-minute bar aggregator. Tích lũy tick → OHLCV bar.
    Flush xuống parquet mỗi BAR_FLUSH_INTERVAL giây.

    Sanity-checks each incoming tick volume against MAX_SINGLE_TICK_VOLUME.
    Suspect ticks are dropped (volume contribution = 0) and counted in
    ``self.suspect_count`` for diagnostics; price-side fields are still
    updated. This protects the warehouse from the WSS accum-vs-delta
    confusion bug that produced 78× inflated volumes on AAA in production.
    """

    def __init__(self):
        # {(ticker, bar_time): {"open", "high", "low", "close", "volume"}}
        self._bars: dict[tuple[str, pd.Timestamp], dict] = {}
        self._lock = threading.Lock()
        # Diagnostics — exposed for tooling
        self.suspect_count = 0
        self._suspect_samples: list[dict] = []   # last 20 suspect entries

    def add_tick(self, ticker: str, tick_time: pd.Timestamp, price: float,
                 volume: float = 0.0):
        """Cập nhật 1m bar với tick mới."""
        bar_time = tick_time.floor("1min")
        key = (ticker, bar_time)
        # Sanity check: huge single-tick volume → almost certainly accum
        # leaked through as delta. Drop the volume contribution.
        try:
            v = float(volume)
        except (TypeError, ValueError):
            v = 0.0
        if v > MAX_SINGLE_TICK_VOLUME or v < 0:
            self.suspect_count += 1
            if len(self._suspect_samples) < 20:
                self._suspect_samples.append({
                    "ticker": ticker,
                    "tick_time": str(tick_time),
                    "rejected_volume": v,
                    "reason": ("absurd magnitude (>"
                               f"{MAX_SINGLE_TICK_VOLUME:,})"
                               if v > MAX_SINGLE_TICK_VOLUME
                               else "negative volume"),
                })
            v = 0.0
        with self._lock:
            bar = self._bars.get(key)
            if bar is None:
                self._bars[key] = {
                    "open": price, "high": price, "low": price,
                    "close": price, "volume": v,
                }
            else:
                bar["high"] = max(bar["high"], price)
                bar["low"] = min(bar["low"], price)
                bar["close"] = price
                bar["volume"] += v

    def diagnostics(self) -> dict:
        """Snapshot of sanity-check counters for `health` / debug."""
        with self._lock:
            return {
                "active_bars": len(self._bars),
                "suspect_count": self.suspect_count,
                "suspect_samples": list(self._suspect_samples),
            }

    def snapshot(self) -> pd.DataFrame:
        """Trả về DataFrame bản sao toàn bộ bars hiện có."""
        with self._lock:
            rows = [
                {
                    "ticker": t, "time": bt,
                    "open": b["open"], "high": b["high"],
                    "low": b["low"], "close": b["close"],
                    "volume": b["volume"],
                }
                for (t, bt), b in self._bars.items()
            ]
        if not rows:
            return pd.DataFrame(columns=["ticker", "time", "open", "high", "low", "close", "volume"])
        return pd.DataFrame(rows).sort_values(["ticker", "time"]).reset_index(drop=True)

    def clear_closed_bars(self, before: pd.Timestamp):
        """Xóa bars trước timestamp chỉ định (sau khi đã flush)."""
        with self._lock:
            keys_to_remove = [k for k in self._bars if k[1] < before]
            for k in keys_to_remove:
                del self._bars[k]


# ═════════════════════════════════════════════════════════════════════════════
# VnStockWSS — main WebSocket client
# ═════════════════════════════════════════════════════════════════════════════

class VnStockWSS:
    """
    Background WebSocket client. Auto-reconnect, singleton-friendly.

    Modes:
      - "wss": kết nối WebSocket tới vnstock_data (nếu có endpoint)
      - "polling": fallback — poll HTTP API mỗi POLL_INTERVAL giây
    """

    POLL_INTERVAL = 2   # seconds — near real-time (25% quota Golden)
    POLL_WORKERS = 16   # parallel HTTP fetchers

    def __init__(self):
        self.mode: str = "polling"  # default fallback
        self.running: bool = False
        self.status: str = "disconnected"  # connected|reconnecting|disconnected|market_closed|error
        self.last_error: Optional[str] = None
        self.subscribed: set[str] = set()
        self.aggregator = BarAggregator()

        # Track last accumulated volume per ticker to convert accum→delta.
        # Price board returns volume as "accumulated from market open". Without
        # this conversion, the BarAggregator would sum accumulated values and
        # inflate daily volume by ~10-30x (one bogus spike per minute × ticks).
        # Reset when accum decreases (new trading day) or first tick.
        self._last_accum_vol: dict[str, float] = {}
        self._last_accum_date: dict[str, str] = {}

        self._ws = None
        self._main_thread: Optional[threading.Thread] = None
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Per-ticker file locks để serialize read-modify-write JSON files
        # (tránh race condition Windows khi nhiều thread ghi cùng 1 file)
        self._file_locks: dict[str, threading.Lock] = {}
        self._file_locks_guard = threading.Lock()

        self._detect_mode()

    def _get_file_lock(self, ticker: str) -> threading.Lock:
        """Lấy hoặc tạo lock cho 1 ticker file. Thread-safe."""
        with self._file_locks_guard:
            lock = self._file_locks.get(ticker)
            if lock is None:
                lock = threading.Lock()
                self._file_locks[ticker] = lock
            return lock

    def _atomic_write_json(self, path: Path, data: dict) -> bool:
        """
        Atomic write JSON với unique tmp name + retry os.replace.
        Windows có thể fail tạm thời do AV scanner, indexer, hoặc reader
        thread (Streamlit đọc file mỗi 3s). Retry với backoff nhỏ.
        """
        import os as _os
        tid = threading.get_ident()
        tmp = path.with_suffix(f".{_os.getpid()}.{tid}.tmp")
        content = json.dumps(data, ensure_ascii=False)

        try:
            tmp.write_text(content)
        except Exception:
            # Cleanup stale tmp
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            raise

        # Retry os.replace — Windows thường bị transient lock
        last_err = None
        for attempt in range(6):
            try:
                _os.replace(str(tmp), str(path))
                return True
            except PermissionError as e:
                last_err = e
                # Exponential-ish backoff: 10ms, 20ms, 40ms, 80ms, 160ms
                time.sleep(0.01 * (2 ** attempt))
            except OSError as e:
                last_err = e
                time.sleep(0.01 * (2 ** attempt))

        # All retries failed — cleanup + re-raise
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        if last_err:
            raise last_err
        raise RuntimeError(f"atomic_write_json failed after retries: {path}")

    # ─────────────────────────────────────────────────────────────────────
    # Mode: polling-only.
    # Confirmed 2026-04 against vnstock_data 3.0.0 (Golden tier): the
    # sponsor package ships REST-only — no WebSocket/streaming API.
    # (A true-WSS scaffold used to live here; see git history if a
    # sponsor release ever ships a WebSocket endpoint.)
    # ─────────────────────────────────────────────────────────────────────
    def _detect_mode(self):
        self.mode = "polling"

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────
    def start(self):
        """Start background threads. Idempotent."""
        with self._lock:
            if self.running:
                return
            self.running = True
            self._stop_event.clear()

        # Cleanup stale .tmp files từ lần chạy trước (orphaned khi process bị kill)
        try:
            self._cleanup_stale_tmp()
        except Exception:
            pass

        # Main data thread (WSS or polling loop)
        self._main_thread = threading.Thread(
            target=self._run_main_loop, daemon=True, name="vnstock-wss-main"
        )
        self._main_thread.start()

    def _cleanup_stale_tmp(self):
        """Xoá các file .tmp orphaned từ lần chạy trước."""
        import os as _os
        for p in LIVE_DIR.glob("*.tmp"):
            try:
                # Parse pattern: {name}.{pid}.{tid}.tmp
                parts = p.stem.rsplit(".", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    stale_pid = int(parts[1])
                    if stale_pid != _os.getpid():
                        p.unlink()
                else:
                    # Legacy .tmp name (no pid) — cũng xoá
                    p.unlink()
            except Exception:
                pass

        # Bar flush thread
        self._flush_thread = threading.Thread(
            target=self._run_flush_loop, daemon=True, name="vnstock-wss-flush"
        )
        self._flush_thread.start()

        self._write_status()

    def stop(self):
        """Stop all threads gracefully."""
        self.running = False
        self._stop_event.set()
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self.status = "disconnected"
        self._write_status()

    def subscribe(self, ticker: str):
        """Subscribe 1 ticker."""
        with self._lock:
            self.subscribed.add(ticker.upper())

    def subscribe_all(self, full_market: bool = False):
        """
        Subscribe symbols.
        full_market=False: VN30 + Index + Futures (38 mã, nhanh)
        full_market=True:  Toàn bộ HOSE+HNX+UPCOM + Index + Futures (~1100+ mã)
        """
        with self._lock:
            if full_market:
                all_stocks = get_all_listed_symbols()
                self.subscribed.update(all_stocks)
                self.subscribed.update(INDEX_SYMBOLS)
                self.subscribed.update(FUTURES_SYMBOLS)
            else:
                self.subscribed.update(ALL_SYMBOLS)
        print(f"[vnstock_wss] Subscribed {len(self.subscribed)} symbols")


    # ─────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────
    def get_status(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "status": self.status,
                "subscribed": sorted(self.subscribed),
                "subscribed_count": len(self.subscribed),
                "error": self.last_error,
                "market_open": self._is_market_open(),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }

    def _write_status(self):
        try:
            self._atomic_write_json(STATUS_PATH, self.get_status())
        except Exception:
            pass

    def _is_market_open(self) -> bool:
        """Kiểm tra có đang trong giờ giao dịch HOSE (Asia/Ho_Chi_Minh)."""
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        except Exception:
            now = datetime.now()
        if now.weekday() >= 5:  # Saturday/Sunday
            return False
        t = now.time()
        return MARKET_OPEN <= t <= MARKET_CLOSE

    # ─────────────────────────────────────────────────────────────────────
    # Main loop — dispatch to WSS or polling
    # ─────────────────────────────────────────────────────────────────────
    def _run_main_loop(self):
        while self.running and not self._stop_event.is_set():
            if not self._is_market_open():
                self.status = "market_closed"
                self._write_status()
                self._stop_event.wait(timeout=30)
                continue

            try:
                self._run_polling_once()
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
                self.status = "error"
                self._write_status()
                self._stop_event.wait(timeout=5)

    # ─────────────────────────────────────────────────────────────────────
    # WSS mode (true WebSocket)
    # ─────────────────────────────────────────────────────────────────────







    # ─────────────────────────────────────────────────────────────────────
    # Polling mode (HTTP fallback)
    # ─────────────────────────────────────────────────────────────────────
    def _run_polling_once(self):
        """
        Poll HTTP API cho toàn bộ symbols subscribed.

        Pipeline:
        1. Stocks + Futures (internal IDs) → Market.price_board(symbols_list)
           → 3 mức depth
        2. Indices → Market.index() per-symbol
        3. Futures (VN30F*) → Quote.price_depth() per-symbol → enrich
           lên 10 mức (overwrite quote file từ step 1)
        """
        self.status = "connected"
        self._write_status()

        with self._lock:
            symbols = sorted(self.subscribed)

        if not symbols:
            self._stop_event.wait(timeout=self.POLL_INTERVAL)
            return

        # ── Split theo loại ───────────────────────────────────────────────
        futures_friendly = [s for s in symbols if is_futures(s) and not s.startswith("41I")]
        indices = [s for s in symbols if s in INDEX_SYMBOLS]
        # Stocks: loại bỏ cả indices VÀ futures (futures được xử lý
        # riêng qua price_depth, không đi qua price_board).
        stocks_only = [s for s in symbols
                       if s not in INDEX_SYMBOLS and not is_futures(s)]

        # ── 1. Batch stocks qua Market.price_board ────────────────────────
        batch_ok = self._fetch_batch_price_board(stocks_only)

        # ── 2. Indices fetch riêng ────────────────────────────────────────
        from concurrent.futures import ThreadPoolExecutor, wait
        if indices:
            pool = ThreadPoolExecutor(max_workers=min(4, len(indices)))
            try:
                futs = [pool.submit(self._fetch_index_quote, i) for i in indices]
                wait(futs, timeout=8)
            finally:
                pool.shutdown(wait=False, cancel_futures=False)

        # ── 3. Volume Profile: chỉ futures (stocks VP fetch on-demand từ dashboard)
        if futures_friendly:
            pool = ThreadPoolExecutor(max_workers=min(4, len(futures_friendly)))
            try:
                futs = [pool.submit(self._fetch_volume_profile, f)
                        for f in futures_friendly]
                wait(futs, timeout=10)
            finally:
                pool.shutdown(wait=False, cancel_futures=False)

        # ── Fallback nếu batch fail ───────────────────────────────────────
        if not batch_ok and stocks_only:
            pool = ThreadPoolExecutor(max_workers=self.POLL_WORKERS)
            try:
                futs = [pool.submit(self._fetch_single_intraday, s)
                        for s in stocks_only]
                wait(futs, timeout=max(self.POLL_INTERVAL - 4, 5))
            finally:
                pool.shutdown(wait=False, cancel_futures=False)

        # Clear transient errors sau successful round.
        # profile/poll/write errors thường transient (AV scanner, reader
        # thread). Batch + index + at least one futures success đủ để
        # coi là "healthy" → xoá error message cũ.
        if batch_ok and self.last_error:
            transient_markers = ("poll", "profile", "write tick", "parquet")
            if any(m in self.last_error.lower() for m in transient_markers):
                self.last_error = None

        self._stop_event.wait(timeout=max(self.POLL_INTERVAL - 5, 1))

    # ─────────────────────────────────────────────────────────────────────
    # Batch fetcher — Market.price_board (PREFERRED)
    # ─────────────────────────────────────────────────────────────────────
    def _fetch_batch_price_board(self, symbols: list[str]) -> bool:
        """
        1 request cho toàn bộ stocks. Trả về True nếu thành công.
        Dùng vnstock_data.Market().price_board(symbols_list).
        """
        if not symbols:
            return True
        try:
            try:
                from vnstock_data import Market  # type: ignore
                ensure_api_key()
                m = Market()
            except ImportError:
                from vnstock_auth import get_vnstock
                m = get_vnstock(symbols[0] if symbols else "VCB")
            # Flexible signature: thử kwarg khác nhau
            df = None
            for call in (
                lambda: m.price_board(symbols_list=symbols),
                lambda: m.price_board(symbols=symbols),
                lambda: m.price_board(symbols),
            ):
                try:
                    df = call()
                    if df is not None and not df.empty:
                        break
                except TypeError:
                    continue
                except Exception:
                    continue
            if df is None or df.empty:
                return False

            # Normalize columns (flatten multi-index if needed)
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = [
                    "_".join(str(x) for x in c if x).strip("_")
                    for c in df.columns.values
                ]
            df.columns = [str(c).lower() for c in df.columns]

            now_iso = datetime.now().isoformat(timespec="seconds")

            # Map flexible column lookups
            def _pick(row, *keys):
                for k in keys:
                    for col in df.columns:
                        if k in col:
                            try:
                                v = row[col]
                                if v is not None and not pd.isna(v):
                                    return float(v)
                            except Exception:
                                continue
                return None

            ticker_col = None
            for candidate in ("listinginfo_symbol", "symbol", "ticker", "code"):
                for col in df.columns:
                    if candidate in col:
                        ticker_col = col
                        break
                if ticker_col:
                    break

            cols_list = list(df.columns)
            count = 0
            for _, row in df.iterrows():
                try:
                    ticker = str(row[ticker_col]).upper() if ticker_col else None
                    if not ticker or ticker == "NAN":
                        continue
                    price = _pick(row, "matchprice", "match_price", "lastprice",
                                  "last", "close", "price")
                    if price is None or price <= 0:
                        continue
                    # `or 0` (bản cũ) GỘP hai ca khác hẳn nhau: "phiên chưa
                    # khớp lệnh nào" và "bảng giá thiếu cột volume tick này".
                    # Ca 2 làm baseline bị ghi đè = 0, nên tick KẾ TIẾP tính
                    # delta = accum CẢ PHIÊN → volume bar phồng (audit 06/08,
                    # cùng họ bug 78× trên AAA). Giữ None để phân biệt.
                    accum_raw = _pick(row, "accumulatedvolume", "accum_volume",
                                      "totalvolume", "volume")
                    accum_volume = accum_raw if accum_raw is not None else 0
                    ref = _pick(row, "refprice", "ref_price", "reference")
                    high = _pick(row, "highest", "high") or price
                    low = _pick(row, "lowest", "low") or price

                    # Convert accumulated → delta for bar aggregation.
                    # First tick (no prior state, or new day): establish a
                    # baseline with delta=0 rather than emitting the full
                    # session-accumulated figure as one bogus bar. Daily
                    # total is filled by the updater API, so missing the
                    # pre-startup volume here is fine.
                    today = now_iso[:10]
                    if accum_raw is None:
                        # Thiếu số liệu tick này: KHÔNG đụng baseline (ghi 0 vào
                        # đó là mồi cho cú phồng ở tick sau), không cộng volume.
                        delta_volume = 0.0
                        accum_volume = self._last_accum_vol.get(ticker, 0)
                    else:
                        delta_volume = accum_to_delta(
                            self._last_accum_vol.get(ticker),
                            self._last_accum_date.get(ticker),
                            accum_volume,
                            today,
                        )
                        self._last_accum_vol[ticker] = accum_volume
                        self._last_accum_date[ticker] = today

                    # price_board chỉ trả 3 mức L2 cho mọi instrument
                    bids = _pick_depth_levels(row, cols_list, "bid", 3)
                    asks = _pick_depth_levels(row, cols_list, "ask", 3)

                    chg_pct = ((price - ref) / ref * 100) if ref else 0

                    tick = {
                        "ticker": ticker,
                        "time": now_iso,
                        "price": price,
                        "volume": accum_volume,  # JSON quote keeps accum (UI shows session total)
                        "_delta_volume": delta_volume,  # aggregator uses delta
                        # Backward compat: best bid/ask
                        "bid": bids[0]["price"] if bids else 0,
                        "ask": asks[0]["price"] if asks else 0,
                        # New: full depth
                        "bids": bids,
                        "asks": asks,
                        "chg_pct": round(chg_pct, 2),
                        "high": high,
                        "low": low,
                        "type": "futures" if is_futures(ticker) else "stock",
                    }
                    self._handle_tick(tick)
                    count += 1
                except Exception:
                    continue

            return count > 0
        except Exception as e:
            self.last_error = f"price_board: {str(e)[:100]}"
            return False

    # ─────────────────────────────────────────────────────────────────────
    # Single-symbol fetchers (fallback)
    # ─────────────────────────────────────────────────────────────────────
    def _fetch_single_intraday(self, ticker: str):
        """Fallback per-stock: Quote.intraday() → _handle_tick."""
        try:
            tick = self._http_fetch_quote(ticker)
            if tick:
                self._handle_tick(tick)
        except Exception as e:
            self.last_error = f"poll {ticker}: {str(e)[:80]}"

    def _fetch_volume_profile(self, ticker: str) -> bool:
        """
        Fetch Volume Profile cho 1 symbol (futures HOẶC stock) qua
        Quote(symbol).price_depth().

        Futures: ghi file quote_VN30F1M.json ĐỘC LẬP (data chính).
        Stocks:  MERGE volume_profile vào quote_VCB.json đã có sẵn
                 (từ price_board) — giữ nguyên price/bid/ask/volume.

        Response format (vnstock_data 3.0.0 / KBS KRX):
            DataFrame: price, buyVol, sellVol, unknownVol, totalVol
        """
        try:
            try:
                from vnstock_data import Quote  # type: ignore
                ensure_api_key()
                q = Quote(symbol=ticker)
            except Exception as e:
                self.last_error = f"Quote({ticker}): {str(e)[:80]}"
                return False

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
                except Exception as e:
                    self.last_error = f"price_depth {ticker}: {str(e)[:60]}"
                    continue

            if df is None or not hasattr(df, "empty") or df.empty:
                self.last_error = f"price_depth {ticker}: empty result"
                return False

            # Normalize columns lowercase
            df = df.copy()
            df.columns = [str(c).lower() for c in df.columns]
            cols = set(df.columns)
            if "price" not in cols or "totalvol" not in cols:
                self.last_error = f"profile {ticker}: unexpected cols {list(cols)}"
                return False

            # DataFrame → list of dicts
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
                self.last_error = f"profile {ticker}: no valid rows"
                return False

            # Giữ top 20 mức theo total_vol
            profile_sorted = sorted(profile, key=lambda r: r["total_vol"], reverse=True)
            top = profile_sorted[:20]
            # Sort theo price để render ladder (cao → thấp)
            top.sort(key=lambda r: r["price"], reverse=True)

            # Tính metadata
            vp_prices = [p["price"] for p in profile]
            total_session_vol = sum(p["total_vol"] for p in profile)
            # "Current" proxy: most active price (highest total_vol)
            most_active_price = profile_sorted[0]["price"] if profile_sorted else 0

            vp_data = {
                "volume_profile": top,
                "volume_profile_total_levels": len(profile),
            }

            path = LIVE_DIR / f"quote_{ticker.upper()}.json"

            if is_futures(ticker):
                # Futures: ghi file độc lập (data chính từ price_depth)
                tick = {
                    "ticker": ticker.upper(),
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "price": most_active_price,
                    "volume": total_session_vol,
                    "bid": 0.0,
                    "ask": 0.0,
                    "bids": [],
                    "asks": [],
                    "chg_pct": 0.0,
                    "high": max(vp_prices) if vp_prices else 0,
                    "low": min(vp_prices) if vp_prices else 0,
                    "type": "futures",
                    **vp_data,
                }
            else:
                # Stocks: merge VP vào quote file đã có (từ price_board)
                tick = {}
                if path.exists():
                    try:
                        tick = json.loads(path.read_text())
                    except Exception:
                        pass
                tick.update(vp_data)

            # Per-ticker lock để serialize
            with self._get_file_lock(ticker.upper()):
                try:
                    self._atomic_write_json(path, tick)
                    return True
                except Exception as e:
                    self.last_error = f"profile write {ticker}: {str(e)[:80]}"
                    return False

        except Exception as e:
            self.last_error = f"profile {ticker} unexpected: {type(e).__name__}: {str(e)[:80]}"
            return False

    def _fetch_index_quote(self, index_name: str):
        """
        Fetch chỉ số (VNINDEX, VN30, ...) qua vnstock_data.Market.index()
        hoặc fallback vnstock.
        """
        try:
            try:
                from vnstock_data import Market  # type: ignore
                ensure_api_key()
                m = Market()
                df = None
                for call in (
                    lambda: m.index(symbol=index_name),
                    lambda: m.index(index_name),
                ):
                    try:
                        df = call()
                        if df is not None and not df.empty:
                            break
                    except TypeError:
                        continue
                    except Exception:
                        continue
                if df is not None and not df.empty:
                    last = df.iloc[-1]
                    self._emit_index_tick(index_name, last)
                    return
            except Exception:
                pass
            # Fallback: vnstock
            tick = self._http_fetch_quote(index_name)
            if tick:
                self._handle_tick(tick)
        except Exception as e:
            self.last_error = f"poll {index_name}: {str(e)[:80]}"

    def _emit_index_tick(self, name: str, row):
        """Convert 1 row từ Market.index() → tick dict."""
        try:
            def _f(r, *keys):
                for k in keys:
                    for col in r.index:
                        if k in str(col).lower():
                            try:
                                v = r[col]
                                if v is not None and not pd.isna(v):
                                    return float(v)
                            except Exception:
                                continue
                return None

            price = _f(row, "close", "last", "price") or 0
            if price <= 0:
                return
            tick = {
                "ticker": name.upper(),
                "time": datetime.now().isoformat(timespec="seconds"),
                "price": price,
                "volume": _f(row, "volume", "vol") or 0,
                "bid": 0.0, "ask": 0.0,
                "bids": [], "asks": [],
                "chg_pct": _f(row, "chg_pct", "change_pct", "pct_change") or 0,
                "high": _f(row, "high") or price,
                "low": _f(row, "low") or price,
                "type": "index",
            }
            self._handle_tick(tick)
        except Exception:
            pass

    def _http_fetch_quote(self, ticker: str) -> Optional[dict]:
        """
        Fallback: dùng HTTP API để lấy quote gần nhất.
        Ưu tiên vnstock_data.Quote (Golden sponsor: 600 req/min) →
        fallback vnstock.Vnstock.
        Lấy bar 1m gần nhất trong 2 ngày gần nhất.
        """
        from datetime import date, timedelta
        df = None
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")

        # Thử vnstock_data trước (sponsor API, ít rate limit hơn)
        try:
            from vnstock_data import Quote  # type: ignore
            ensure_api_key()
            q = Quote(symbol=ticker)
            df = q.history(start=start, end=end, interval="1m")
        except Exception:
            df = None

        # Fallback: vnstock free
        if df is None or (hasattr(df, "empty") and df.empty):
            try:
                from vnstock_auth import get_vnstock
                stock = get_vnstock(ticker)
                df = stock.quote.history(start=start, end=end, interval="1m")
            except Exception as e:
                self.last_error = f"http fetch {ticker}: {str(e)[:80]}"
                return None

        if df is None or df.empty:
            return None

        # Normalize column names
        col_map = {}
        for c in df.columns:
            cl = str(c).lower()
            if cl in ("time", "date", "tradingdate"):
                col_map[c] = "time"
            elif cl in ("close", "adjclose"):
                col_map[c] = "close"
            elif cl in ("volume", "vol"):
                col_map[c] = "volume"
            elif cl in ("high",):
                col_map[c] = "high"
            elif cl in ("low",):
                col_map[c] = "low"
        df = df.rename(columns=col_map)

        if "close" not in df.columns:
            return None

        last = df.iloc[-1]
        price = float(last.get("close", 0))
        if price <= 0:
            return None

        # Tính chg_pct so với close đầu tiên trong window (proxy cho giá mở cửa)
        prev_close = float(df.iloc[0].get("close", price)) if len(df) > 1 else price
        chg_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

        t_upper = ticker.upper()
        return {
            "ticker": t_upper,
            "time": str(last.get("time", datetime.now().isoformat(timespec="seconds"))),
            "price": price,
            "volume": float(last.get("volume", 0)),
            "bid": 0.0,
            "ask": 0.0,
            "bids": [],
            "asks": [],
            "chg_pct": round(chg_pct, 2),
            "high": float(last.get("high", price)),
            "low": float(last.get("low", price)),
            "type": "futures" if is_futures(t_upper) else "stock",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Tick handler — write Tầng 1 + update Tầng 2
    # ─────────────────────────────────────────────────────────────────────
    def _handle_tick(self, tick: dict):
        """Xử lý 1 tick: ghi JSON Tầng 1 + aggregate Tầng 2."""
        ticker = tick["ticker"]
        path = LIVE_DIR / f"quote_{ticker}.json"

        # Per-ticker lock để serialize concurrent writes
        with self._get_file_lock(ticker):
            try:
                self._atomic_write_json(path, tick)
            except Exception as e:
                self.last_error = f"write tick {ticker}: {str(e)[:100]}"

        # Tầng 2: aggregate 1m bar (ngoài lock vì aggregator có lock riêng)
        # Prefer _delta_volume (already converted from accum) over raw "volume"
        # which may be accumulated session total — adding accum would inflate bars.
        try:
            tick_time = pd.to_datetime(tick["time"])
            if tick_time.tz is not None:
                tick_time = tick_time.tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
            # Không có `_delta_volume` → KHÔNG cộng volume (audit 06/08).
            # Bản cũ rơi về `tick["volume"]`, mà 3 nguồn tick khác price_board
            # đều đặt vào đó số TÍCH LUỸ: fallback intraday (bar mới nhất),
            # index, và futures (`total_session_vol`). Vòng poll ~1s cộng lại
            # con số đó MỖI LẦN → bar phồng nhiều lần. Mặc định an toàn: chỉ
            # tick nào TỰ KHAI delta mới được đóng góp volume; giá vẫn cập
            # nhật bình thường. Tổng ngày do updater API lấp (cùng lý lẽ với
            # baseline delta=0 ở tick đầu phiên).
            bar_volume = tick.get("_delta_volume") or 0.0
            self.aggregator.add_tick(
                ticker, tick_time, tick["price"], bar_volume
            )
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────
    # Bar flush loop — Tầng 2 → parquet mỗi BAR_FLUSH_INTERVAL
    # ─────────────────────────────────────────────────────────────────────
    def _run_flush_loop(self):
        while self.running and not self._stop_event.is_set():
            self._stop_event.wait(timeout=BAR_FLUSH_INTERVAL)
            if not self.running:
                break
            try:
                self._flush_bars()
            except Exception as e:
                self.last_error = f"flush error: {str(e)[:100]}"

    def _flush_bars(self):
        """Append bars in-memory → parquet file cho ngày hiện tại."""
        snap = self.aggregator.snapshot()
        if snap.empty:
            return

        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = LIVE_DIR / f"bars_{date_str}.parquet"

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            # Merge với file hiện tại nếu có
            if out_path.exists():
                existing = pq.read_table(str(out_path)).to_pandas()
                combined = pd.concat([existing, snap], ignore_index=True)
                combined = combined.drop_duplicates(
                    subset=["ticker", "time"], keep="last"
                )
            else:
                combined = snap

            table = pa.Table.from_pandas(combined, preserve_index=False)
            import os as _os
            tid = threading.get_ident()
            tmp = out_path.with_suffix(f".{_os.getpid()}.{tid}.tmp")
            try:
                pq.write_table(table, str(tmp), compression="snappy")
                _os.replace(str(tmp), str(out_path))
            except Exception:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                raise
        except Exception as e:
            self.last_error = f"parquet flush: {str(e)[:100]}"


# ═════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═════════════════════════════════════════════════════════════════════════════

_instance: Optional[VnStockWSS] = None
_instance_lock = threading.Lock()


def get_wss_client() -> VnStockWSS:
    """Singleton accessor — 1 client/process."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = VnStockWSS()
    return _instance


# ═════════════════════════════════════════════════════════════════════════════
# CLI — smoke test
# ═════════════════════════════════════════════════════════════════════════════



def _health_check():
    """
    Kiểm tra tình trạng live data + warehouse.
    In báo cáo tổng quan: files tươi/stale, kích thước, symbols thiếu,
    price anomalies.
    """
    print("=" * 60)
    print("vnstock_wss Health Check")
    print("=" * 60)

    now = datetime.now()
    stats = {"ok": 0, "warn": 0, "err": 0}

    def _ok(msg): print(f"  ✓ {msg}"); stats["ok"] += 1
    def _warn(msg): print(f"  ⚠ {msg}"); stats["warn"] += 1
    def _err(msg): print(f"  ✗ {msg}"); stats["err"] += 1

    # ── 1. LIVE_DIR existence ────────────────────────────────────────────
    print(f"\n[1/6] Live directory: {LIVE_DIR}")
    if not LIVE_DIR.exists():
        _err("LIVE_DIR does not exist — WSS client chưa chạy bao giờ?")
        return stats
    _ok(f"LIVE_DIR exists")

    # ── 2. Quote file freshness ──────────────────────────────────────────
    print(f"\n[2/6] Quote file freshness")
    all_quotes = list(LIVE_DIR.glob("quote_*.json"))
    if not all_quotes:
        _warn("Không có quote file nào (WSS client chưa subscribe?)")
    else:
        fresh = 0
        stale = 0
        for p in all_quotes:
            age = now.timestamp() - p.stat().st_mtime
            if age < 300:  # 5 minutes
                fresh += 1
            else:
                stale += 1
        _ok(f"{fresh}/{len(all_quotes)} files fresh (<5 min old)")
        if stale > 0:
            _warn(f"{stale} stale files (>5 min old)")

    # ── 3. Required symbols coverage ─────────────────────────────────────
    print(f"\n[3/6] Required symbols coverage")
    required = set(VN30_SYMBOLS + INDEX_SYMBOLS)
    present = set()
    for p in all_quotes:
        name = p.stem.replace("quote_", "")
        if name in required:
            present.add(name)
    missing = required - present
    if not missing:
        _ok(f"All {len(required)} required symbols present")
    else:
        _warn(f"Missing {len(missing)}: {sorted(missing)}")

    # Futures (friendly names)
    fut_files = [p.stem.replace("quote_", "")
                 for p in LIVE_DIR.glob("quote_VN30F*.json")]
    if fut_files:
        _ok(f"Futures with VP: {len(fut_files)} ({', '.join(sorted(fut_files))})")
    else:
        _warn("Không có futures VP file nào")

    # ── 4. Price anomalies ───────────────────────────────────────────────
    print(f"\n[4/6] Price anomalies")
    anomalies = 0
    for p in all_quotes:
        try:
            q = json.loads(p.read_text())
            price = float(q.get("price", 0))
            chg = abs(float(q.get("chg_pct", 0)))
            if price <= 0:
                _warn(f"{p.stem}: price={price}")
                anomalies += 1
            elif chg > 10:  # Giá thay đổi > 10% trong ngày
                _warn(f"{p.stem}: chg_pct={chg:+.2f}% (unusual)")
                anomalies += 1
        except Exception:
            continue
    if anomalies == 0:
        _ok("No price anomalies detected")

    # ── 5. Bars parquet ──────────────────────────────────────────────────
    print(f"\n[5/6] Bars parquet (1m aggregated)")
    today_bars = LIVE_DIR / f"bars_{now.date().isoformat()}.parquet"
    if today_bars.exists():
        size = today_bars.stat().st_size
        _ok(f"{today_bars.name}: {size:,} bytes")
        if size < 1024:
            _warn(f"Size < 1KB — có thể chưa flush đủ data")
    else:
        _warn(f"{today_bars.name} chưa tồn tại "
              f"(sẽ được tạo sau flush đầu tiên, mỗi 60s)")

    # ── 6. Stale tmp files ───────────────────────────────────────────────
    print(f"\n[6/6] Stale tmp files")
    stale_tmps = list(LIVE_DIR.glob("*.tmp"))
    if not stale_tmps:
        _ok("No stale tmp files")
    else:
        _warn(f"{len(stale_tmps)} stale tmp file(s) — sẽ được cleanup ở start()")
        for t in stale_tmps[:5]:
            print(f"      {t.name}")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"Summary: {stats['ok']} OK | {stats['warn']} WARN | {stats['err']} ERROR")
    print("=" * 60)
    return stats




def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="vnstock_wss CLI")
    parser.add_argument("--test", action="store_true", help="Run 60s smoke test")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--probe-profile", metavar="TICKER",
                        help="Run _fetch_volume_profile (use ALL for all futures)")
    parser.add_argument("--health-check", action="store_true",
                        help="Report live data + warehouse health")
    parser.add_argument("--duration", type=int, default=60, help="Test duration (s)")
    args = parser.parse_args()

    if args.health_check:
        _health_check()
        return

    if args.probe_profile:
        # Chạy _fetch_volume_profile cho 1 hoặc ALL futures
        client = get_wss_client()
        from vnstock_wss import FUTURES_SYMBOLS as _FS

        # Nếu argument là "ALL", probe tất cả futures
        targets = _FS if args.probe_profile.upper() == "ALL" else [args.probe_profile]

        for tkr in targets:
            print(f"\n{'─'*60}")
            print(f"[probe-profile] {tkr}")
            client.last_error = None
            ok = client._fetch_volume_profile(tkr)
            print(f"  Success: {ok}")
            print(f"  last_error: {client.last_error}")
            fpath = LIVE_DIR / f"quote_{tkr.upper()}.json"
            if fpath.exists():
                q = json.loads(fpath.read_text())
                vp = q.get("volume_profile", [])
                print(f"  {fpath.name}: {len(vp)} volume profile rows "
                      f"(total levels in phiên: {q.get('volume_profile_total_levels', 0)})")
                print(f"  File price: {q.get('price')}, high: {q.get('high')}, "
                      f"low: {q.get('low')}")
                if vp:
                    print(f"  Top 3 by total_vol: "
                          f"{[{'p': r['price'], 'tv': r['total_vol']} for r in vp[:3]]}")
            else:
                print(f"  File {fpath.name} not created")
        return

    client = get_wss_client()

    if args.status:
        print(json.dumps(client.get_status(), indent=2, ensure_ascii=False))
        return

    if args.test:
        print(f"[vnstock_wss] Starting {args.duration}s smoke test...")
        print(f"  Mode: {client.mode}")
        client.start()
        client.subscribe_all()

        start = time.time()
        while time.time() - start < args.duration:
            time.sleep(5)
            status = client.get_status()
            print(f"  [{int(time.time()-start):3d}s] status={status['status']} "
                  f"subscribed={status['subscribed_count']} "
                  f"error={status.get('error', '')[:50] if status.get('error') else '-'}")

        print("\n[vnstock_wss] Flushing bars...")
        client._flush_bars()

        print("\n[vnstock_wss] Final status:")
        print(json.dumps(client.get_status(), indent=2, ensure_ascii=False))

        print(f"\n[vnstock_wss] Files in {LIVE_DIR}:")
        for f in sorted(LIVE_DIR.glob("*")):
            size = f.stat().st_size
            print(f"  {f.name}  ({size} bytes)")

        client.stop()
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()
