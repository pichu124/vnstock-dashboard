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
import sys
import time
import threading
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

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

ALL_SYMBOLS = VN30_SYMBOLS + INDEX_SYMBOLS

LIVE_DIR = Path("data_warehouse/_live")
LIVE_DIR.mkdir(parents=True, exist_ok=True)

STATUS_PATH = LIVE_DIR / "status.json"

# HOSE trading hours (Asia/Ho_Chi_Minh, UTC+7)
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 0)

# Bar flush interval (seconds)
BAR_FLUSH_INTERVAL = 60


# ═════════════════════════════════════════════════════════════════════════════
# BarAggregator — aggregate ticks → 1m OHLCV bars in-memory
# ═════════════════════════════════════════════════════════════════════════════

class BarAggregator:
    """
    In-memory 1-minute bar aggregator. Tích lũy tick → OHLCV bar.
    Flush xuống parquet mỗi BAR_FLUSH_INTERVAL giây.
    """

    def __init__(self):
        # {(ticker, bar_time): {"open", "high", "low", "close", "volume"}}
        self._bars: dict[tuple[str, pd.Timestamp], dict] = {}
        self._lock = threading.Lock()

    def add_tick(self, ticker: str, tick_time: pd.Timestamp, price: float,
                 volume: float = 0.0):
        """Cập nhật 1m bar với tick mới."""
        bar_time = tick_time.floor("1min")
        key = (ticker, bar_time)
        with self._lock:
            bar = self._bars.get(key)
            if bar is None:
                self._bars[key] = {
                    "open": price, "high": price, "low": price,
                    "close": price, "volume": float(volume),
                }
            else:
                bar["high"] = max(bar["high"], price)
                bar["low"] = min(bar["low"], price)
                bar["close"] = price
                bar["volume"] += float(volume)

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

    POLL_INTERVAL = 10  # seconds (fallback mode)

    def __init__(self):
        self.mode: str = "polling"  # default fallback
        self.running: bool = False
        self.status: str = "disconnected"  # connected|reconnecting|disconnected|market_closed|error
        self.last_error: Optional[str] = None
        self.subscribed: set[str] = set()
        self.aggregator = BarAggregator()

        self._ws = None
        self._main_thread: Optional[threading.Thread] = None
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._detect_mode()

    # ─────────────────────────────────────────────────────────────────────
    # Mode detection — check if vnstock_data sponsor has realtime API
    # ─────────────────────────────────────────────────────────────────────
    def _detect_mode(self):
        """
        Thử import vnstock_data và detect WSS endpoint. Nếu không có,
        rơi về polling mode.
        """
        try:
            import vnstock_data  # noqa: F401
            # Check các attribute có khả năng là realtime/streaming API
            candidates = ["Realtime", "Stream", "WebSocket", "Live", "Quote"]
            has_realtime = any(hasattr(vnstock_data, c) for c in candidates)
            if has_realtime:
                self.mode = "wss"
                print("[vnstock_wss] Detected vnstock_data realtime API → WSS mode")
            else:
                self.mode = "polling"
                print("[vnstock_wss] vnstock_data found but no realtime API → polling mode")
        except ImportError:
            self.mode = "polling"
            print("[vnstock_wss] vnstock_data not installed → polling mode")

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

        # Main data thread (WSS or polling loop)
        self._main_thread = threading.Thread(
            target=self._run_main_loop, daemon=True, name="vnstock-wss-main"
        )
        self._main_thread.start()

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

    def subscribe_all(self):
        """Subscribe toàn bộ VN30 + Index."""
        with self._lock:
            self.subscribed.update(ALL_SYMBOLS)
        print(f"[vnstock_wss] Subscribed {len(self.subscribed)} symbols")

    def unsubscribe(self, ticker: str):
        with self._lock:
            self.subscribed.discard(ticker.upper())

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
            tmp = STATUS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.get_status(), ensure_ascii=False))
            tmp.replace(STATUS_PATH)
        except Exception:
            pass

    def _is_market_open(self) -> bool:
        """Kiểm tra có đang trong giờ giao dịch HOSE (Asia/Ho_Chi_Minh)."""
        try:
            import pytz
            vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
            now = datetime.now(vn_tz)
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
                if self.mode == "wss":
                    self._run_wss_once()
                else:
                    self._run_polling_once()
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
                self.status = "error"
                self._write_status()
                self._stop_event.wait(timeout=5)

    # ─────────────────────────────────────────────────────────────────────
    # WSS mode (true WebSocket)
    # ─────────────────────────────────────────────────────────────────────
    def _run_wss_once(self):
        """
        Kết nối WebSocket và chạy run_forever. Khi disconnect, main loop
        sẽ retry.
        """
        try:
            import websocket
        except ImportError:
            self.last_error = "websocket-client not installed (pip install websocket-client)"
            self.status = "error"
            self.mode = "polling"  # fallback
            return

        url = self._get_wss_endpoint()
        if not url:
            # Không có endpoint → fallback polling
            self.mode = "polling"
            return

        self.status = "reconnecting"
        self._write_status()

        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)

    def _get_wss_endpoint(self) -> Optional[str]:
        """
        Thử lấy WSS endpoint từ vnstock_data. Trả về None nếu không tìm được.
        TODO: update khi xác định được endpoint thực tế từ sponsor package.
        """
        try:
            import vnstock_data
            # Thử các attribute có thể chứa endpoint
            for attr in ("WSS_URL", "REALTIME_URL", "STREAM_URL"):
                if hasattr(vnstock_data, attr):
                    return getattr(vnstock_data, attr)
        except Exception:
            pass
        return None

    def _on_ws_open(self, ws):
        self.status = "connected"
        self._write_status()
        # Send subscribe message(s) — format phụ thuộc provider
        try:
            with self._lock:
                symbols = list(self.subscribed)
            sub_msg = json.dumps({"action": "subscribe", "symbols": symbols})
            ws.send(sub_msg)
        except Exception as e:
            self.last_error = f"subscribe failed: {e}"

    def _on_ws_message(self, ws, raw):
        try:
            msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
            tick = self._parse_tick(msg)
            if tick:
                self._handle_tick(tick)
        except Exception as e:
            self.last_error = f"parse error: {str(e)[:100]}"

    def _on_ws_error(self, ws, err):
        self.last_error = f"ws error: {str(err)[:200]}"
        self.status = "error"
        self._write_status()

    def _on_ws_close(self, ws, code, msg):
        self.status = "disconnected"
        self._write_status()

    def _parse_tick(self, msg: dict) -> Optional[dict]:
        """
        Normalize tick message từ provider → format chuẩn.
        TODO: implement khi biết schema của vnstock_data.
        """
        # Placeholder — try common field names
        try:
            ticker = msg.get("symbol") or msg.get("ticker") or msg.get("s")
            price = msg.get("price") or msg.get("close") or msg.get("p")
            if not ticker or price is None:
                return None
            return {
                "ticker": str(ticker).upper(),
                "time": msg.get("time") or datetime.now().isoformat(timespec="seconds"),
                "price": float(price),
                "volume": float(msg.get("volume", 0) or msg.get("v", 0) or 0),
                "bid": float(msg.get("bid", 0) or 0),
                "ask": float(msg.get("ask", 0) or 0),
                "chg_pct": float(msg.get("chg_pct", 0) or msg.get("change_pct", 0) or 0),
                "high": float(msg.get("high", price) or price),
                "low": float(msg.get("low", price) or price),
            }
        except Exception:
            return None

    # ─────────────────────────────────────────────────────────────────────
    # Polling mode (HTTP fallback)
    # ─────────────────────────────────────────────────────────────────────
    def _run_polling_once(self):
        """
        Poll HTTP API cho toàn bộ symbols subscribed. Chạy song song
        bằng ThreadPoolExecutor để nhanh.
        """
        self.status = "connected"  # polling được coi như "connected"
        self._write_status()

        with self._lock:
            symbols = sorted(self.subscribed)

        if not symbols:
            self._stop_event.wait(timeout=self.POLL_INTERVAL)
            return

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _poll_one(sym: str):
            try:
                tick = self._http_fetch_quote(sym)
                if tick:
                    self._handle_tick(tick)
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_poll_one, s) for s in symbols]
            for _ in as_completed(futures, timeout=self.POLL_INTERVAL - 2):
                pass

        self._stop_event.wait(timeout=self.POLL_INTERVAL)

    def _http_fetch_quote(self, ticker: str) -> Optional[dict]:
        """
        Fallback: dùng vnstock/vnstock_data HTTP API để lấy quote gần nhất.
        Lấy bar 1m cuối cùng từ quote.history().
        """
        try:
            try:
                from vnstock_data import Quote  # type: ignore
                q = Quote(symbol=ticker, source="VCI")
                df = q.history(interval="1m", page_size=2)
            except Exception:
                from vnstock import Vnstock
                from datetime import date, timedelta
                end = date.today().strftime("%Y-%m-%d")
                start = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
                stock = Vnstock().stock(symbol=ticker, source="VCI")
                df = stock.quote.history(start=start, end=end, interval="1m")

            if df is None or df.empty:
                return None

            last = df.iloc[-1]
            price = float(last.get("close", 0))
            if price <= 0:
                return None

            prev_close = float(df.iloc[0].get("close", price)) if len(df) > 1 else price
            chg_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

            return {
                "ticker": ticker.upper(),
                "time": str(last.get("time", datetime.now().isoformat(timespec="seconds"))),
                "price": price,
                "volume": float(last.get("volume", 0)),
                "bid": 0.0,
                "ask": 0.0,
                "chg_pct": round(chg_pct, 2),
                "high": float(last.get("high", price)),
                "low": float(last.get("low", price)),
            }
        except Exception as e:
            self.last_error = f"http fetch {ticker}: {str(e)[:100]}"
            return None

    # ─────────────────────────────────────────────────────────────────────
    # Tick handler — write Tầng 1 + update Tầng 2
    # ─────────────────────────────────────────────────────────────────────
    def _handle_tick(self, tick: dict):
        """Xử lý 1 tick: ghi JSON Tầng 1 + aggregate Tầng 2."""
        ticker = tick["ticker"]
        # Tầng 1: atomic write JSON
        try:
            path = LIVE_DIR / f"quote_{ticker}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(tick, ensure_ascii=False))
            tmp.replace(path)
        except Exception as e:
            self.last_error = f"write tick {ticker}: {str(e)[:100]}"

        # Tầng 2: aggregate 1m bar
        try:
            tick_time = pd.to_datetime(tick["time"])
            if tick_time.tz is not None:
                tick_time = tick_time.tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
            self.aggregator.add_tick(
                ticker, tick_time, tick["price"], tick.get("volume", 0)
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
            tmp = out_path.with_suffix(".tmp")
            pq.write_table(table, str(tmp), compression="snappy")
            tmp.replace(out_path)
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

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="vnstock_wss CLI")
    parser.add_argument("--test", action="store_true", help="Run 60s smoke test")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--duration", type=int, default=60, help="Test duration (s)")
    args = parser.parse_args()

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
