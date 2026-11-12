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

# ⚠️ HẰNG SỐ NÀY LÀ LƯỚI CUỐI, KHÔNG PHẢI NGUỒN SỰ THẬT.
# HOSE xét lại rổ VN30 hai lần mỗi năm ⇒ danh sách chép cứng sẽ SAI sau mỗi
# kỳ (vết 20/08/2026: heatmap live vẽ rổ cũ). Nguồn thật là
# `vnstock_vn30.get_members()` (API sống → cache `_meta/vn30_members.json` →
# hằng số này). Dùng `get_vn30_symbols()` ở mọi chỗ cần rổ hiện hành.
VN30_SYMBOLS = [
    "ACB", "BID", "BSR", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG", "LPB",
    "MBB", "MCH", "MSN", "MWG", "SAB", "SHB", "SSB", "SSI", "STB", "TCB",
    "TCX", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VPL", "VRE",
]


def get_vn30_symbols() -> list[str]:
    """Rổ VN30 hiện hành. Không bao giờ ném — xấu nhất trả VN30_SYMBOLS."""
    try:
        import vnstock_vn30
        return vnstock_vn30.get_members()
    except Exception:
        return list(VN30_SYMBOLS)

_HOT_TIER_ENV = "VNSTOCK_WSS_HOT_TIER"


def hot_tier_enabled() -> bool:
    """Kill-switch tầng nóng: đặt VNSTOCK_WSS_HOT_TIER=0 để quét đều như cũ."""
    return os.environ.get(_HOT_TIER_ENV, "1").strip().lower() \
        not in ("0", "false", "no")


def split_hot_cold(symbols, hot_set, cycle: int, every_n: int = 5,
                   tiering: bool = True) -> list[str]:
    """
    Chọn danh sách mã cho vòng poll thứ ``cycle``. HÀM THUẦN.

    Vòng chia hết cho ``every_n`` quét TẤT CẢ; vòng khác chỉ quét mã nóng.
    Không có mã nóng nào (hoặc tắt tiering) ⇒ trả nguyên danh sách — không
    bao giờ trả rỗng khi đầu vào khác rỗng, vì một vòng quét rỗng là feed
    đứng hình mà status vẫn "connected".
    """
    if not symbols:
        return []
    if not tiering or every_n <= 1:
        return list(symbols)
    hot = [s for s in symbols if s in hot_set]
    if not hot or len(hot) == len(symbols):
        return list(symbols)
    if cycle % every_n == 0:
        return list(symbols)
    return hot


INDEX_SYMBOLS = ["VNINDEX", "VN30", "HNXINDEX", "HNX30"]


FUTURES_SYMBOLS = ["VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q"]


def _index_quote_last_row(df: pd.DataFrame) -> pd.Series:
    """Dòng MỚI NHẤT của `Market().index(s).quote()` (thế hệ 6 trả CẢ chuỗi trong ngày — đo 🖥️ 12/11:
    4.144 dòng), chỉ giữ đúng cột `_emit_index_tick` cần (hàm đó dò tên theo chuỗi con: để lại
    `put_through_volume`, `advance_volume`… là nó vớ nhầm). Khối lượng phiên: CHƯA đo được cột nào là
    luỹ kế cả phiên (`total_volume` hay `accumulated_volume`) ⇒ lấy số LỚN HƠN của hai cột — cột luỹ kế
    luôn lớn nhất; xác nhận bằng `scripts/gen6_check.py` (in đầu/cuối chuỗi). Hàm thuần."""
    if "time" in df.columns:
        df = df.assign(_t=pd.to_datetime(df["time"], errors="coerce")).sort_values(
            "_t", kind="stable", na_position="first")          # time hỏng không thành "mới nhất"
    row = df.iloc[-1]
    vols = [v for v in (pd.to_numeric(row.get(c), errors="coerce")
                        for c in ("total_volume", "accumulated_volume")) if pd.notna(v)]
    keep = {"close": row.get("close_price"), "high": row.get("high_price"),
            "low": row.get("low_price"), "volume": max(vols) if vols else None,
            "reference_price": row.get("reference_price")}
    return pd.Series(keep)


def is_futures(ticker: str) -> bool:
    """
    Check nếu ticker là hợp đồng tương lai VN30.

    Nhận diện 3 format:
    - Friendly names: VN30F1M, VN30F2M, VN30F1Q, VN30F2Q
    - Expiry codes:   VN30F2410, VN30F2504 (YYMM)
    - HNX internal:   41I1G4000, 41I1G5000, ... (bảng giá HĐTL trả về)
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
        from vnstock import Reference
        from vnstock.errors import VnstockError
        ensure_api_key()
        ref = Reference()
        for exchange in ("HOSE", "HNX", "UPCOM"):
            try:
                df = ref.equity.list(exchange=exchange)
            except VnstockError as e:
                print(f"[vnstock_wss] Reference().equity.list({exchange}) lỗi: "
                      f"{getattr(e, 'code', type(e).__name__)}: {str(e)[:120]}")
                continue
            if df is not None and not df.empty and "symbol" in df.columns:
                symbols.extend(df["symbol"].dropna().astype(str).str.upper().tolist())
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
# Depth parser — parse multi-level bid/ask từ 1 dòng bảng giá (quote)
# ═════════════════════════════════════════════════════════════════════════════

def _pick_depth_levels(row, columns: list, side: str,
                       max_levels: int = 10) -> list[dict]:
    """
    Parse bid/ask levels từ 1 row của bảng giá (`Market().equity.quote`, thế hệ 6:
    `bid_price_N`/`bid_vol_N`, `ask_price_N`/`ask_vol_N`).
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


def _ensure_live_dir() -> bool:
    """Tạo LIVE_DIR khi CẦN GHI — cố gắng hết sức, không bao giờ ném lỗi.

    Trước 06/08 đây là `LIVE_DIR.mkdir(...)` chạy thẳng ở CẤP MODULE: hỏng
    một lần là cả module KHÔNG IMPORT ĐƯỢC, kéo theo dashboard lẫn test.
    Máy user (Windows) đỏ 4 test đúng vì vậy — `mkdir(exist_ok=True)` VẪN
    ném `FileExistsError` khi `Path.is_dir()` trả False, mà `is_dir()` nuốt
    mọi OSError của `stat` (ACL chặn, reparse point hỏng, file bị khoá) rồi
    trả False. Nói cách khác: thư mục có thật vẫn làm import chết.

    Trả về True nếu thư mục dùng được. Chỗ ghi tự gọi hàm này nên không cần
    side effect lúc import nữa.
    """
    try:
        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        try:
            return LIVE_DIR.exists()   # đã có sẵn → cứ để bước ghi thử tiếp
        except OSError:
            return False


_ensure_live_dir()          # tiện thì tạo sẵn, hỏng cũng KHÔNG chặn import

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
      - "wss": chưa dùng (vnstock thế hệ 6 chỉ có REST)
      - "polling": fallback — poll HTTP API mỗi POLL_INTERVAL giây
    """

    POLL_INTERVAL = 2   # seconds — near real-time (25% quota Golden)
    # ── Tầng NÓNG (20/08) ────────────────────────────────────────────────
    # `full_market=True` subscribe ~1.100 mã, và MỖI vòng poll gọi
    # price_board cho CẢ 1.100 rồi ghi ~1.100 file JSON — nên một quote VN30
    # chỉ tươi lại sau trọn một vòng quét toàn thị trường. Heatmap chỉ cần 30
    # mã. Tách hai tầng: mã NÓNG (VN30 + index + futures) quét MỖI vòng, phần
    # còn lại quét mỗi COLD_EVERY_N vòng. Live Scan của Screener/Dòng Tiền
    # chậm lại đúng chừng đó — đổi lấy heatmap bám tick.
    # Với `full_market=False` (38 mã) thì cold rỗng ⇒ hành vi KHÔNG đổi.
    COLD_EVERY_N = 5
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

        # Nhịp poll — dùng cho tầng nóng/lạnh + đo thời gian vòng quét.
        # Không đo được thì không chẩn đoán được "heatmap chậm" là do đâu.
        self._poll_cycle: int = 0
        self._last_cycle_s: float | None = None
        self._last_batch_s: float | None = None
        self._last_batch_n: int = 0
        self._hot_cache: frozenset[str] = frozenset()

        self._detect_mode()

    def _hot_set(self) -> frozenset[str]:
        """Mã cần tươi MỖI vòng: rổ VN30 hiện hành + index + futures."""
        if not self._hot_cache:
            self._hot_cache = frozenset(get_vn30_symbols()) \
                | frozenset(INDEX_SYMBOLS) | frozenset(FUTURES_SYMBOLS)
        return self._hot_cache

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
        _ensure_live_dir()      # tạo lúc GHI, không phải lúc import
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
    # vnstock thế hệ 6 (như vnstock_data 3.0.0 trước đó) chỉ có REST —
    # không có WebSocket/streaming API. (A true-WSS scaffold used to live
    # here; see git history if a release ever ships a WebSocket endpoint.)
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
                self.subscribed.update(get_vn30_symbols())
                self.subscribed.update(INDEX_SYMBOLS)
                self.subscribed.update(FUTURES_SYMBOLS)
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
                # Nhịp thật của vòng quét — "heatmap chậm" chẩn đoán từ đây,
                # không phải từ cảm giác.
                "cycle_s": self._last_cycle_s,
                "batch_s": self._last_batch_s,
                "batch_n": self._last_batch_n,
                "hot_tier": hot_tier_enabled(),
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
        1. Stocks → Market().equity.quote(symbols) → 3 mức depth
        2. Indices → Market().index(s).quote() per-symbol
        3. Futures (VN30F*) → Market().futures(s).quote() per-symbol
        """
        self.status = "connected"
        self._write_status()
        _t_cycle = time.time()

        with self._lock:
            symbols = sorted(self.subscribed)

        if not symbols:
            self._stop_event.wait(timeout=self.POLL_INTERVAL)
            return

        # ── Split theo loại ───────────────────────────────────────────────
        futures_friendly = [s for s in symbols if is_futures(s) and not s.startswith("41I")]
        indices = [s for s in symbols if s in INDEX_SYMBOLS]
        # Stocks: loại bỏ cả indices VÀ futures (futures được xử lý
        # riêng qua Market().futures(s).quote(), không đi qua bảng giá cổ phiếu).
        stocks_only = [s for s in symbols
                       if s not in INDEX_SYMBOLS and not is_futures(s)]

        # ── Tầng nóng/lạnh ────────────────────────────────────────────────
        cycle = self._poll_cycle
        self._poll_cycle += 1
        batch_symbols = split_hot_cold(stocks_only, self._hot_set(), cycle,
                                       every_n=self.COLD_EVERY_N,
                                       tiering=hot_tier_enabled())

        # ── 1. Batch stocks qua Market().equity.quote ─────────────────────
        _t_batch = time.time()
        batch_ok = self._fetch_batch_price_board(batch_symbols)
        self._last_batch_s = round(time.time() - _t_batch, 2)
        self._last_batch_n = len(batch_symbols)

        # ── 2. Indices fetch riêng ────────────────────────────────────────
        from concurrent.futures import ThreadPoolExecutor, wait
        if indices:
            pool = ThreadPoolExecutor(max_workers=min(4, len(indices)))
            try:
                futs = [pool.submit(self._fetch_index_quote, i) for i in indices]
                wait(futs, timeout=8)
            finally:
                pool.shutdown(wait=False, cancel_futures=False)

        # ── 3. Futures: bảng giá từng HĐTL (stocks VP fetch on-demand từ dashboard)
        if futures_friendly:
            pool = ThreadPoolExecutor(max_workers=min(4, len(futures_friendly)))
            try:
                futs = [pool.submit(self._fetch_futures_quote, f)
                        for f in futures_friendly]
                wait(futs, timeout=10)
            finally:
                pool.shutdown(wait=False, cancel_futures=False)

        # ── Fallback nếu batch fail ───────────────────────────────────────
        if not batch_ok and batch_symbols:
            pool = ThreadPoolExecutor(max_workers=self.POLL_WORKERS)
            try:
                futs = [pool.submit(self._fetch_single_intraday, s)
                        for s in batch_symbols]
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

        self._last_cycle_s = round(time.time() - _t_cycle, 2)
        self._stop_event.wait(timeout=max(self.POLL_INTERVAL - 5, 1))

    # ─────────────────────────────────────────────────────────────────────
    # Batch fetcher — Market().equity.quote (PREFERRED)
    # ─────────────────────────────────────────────────────────────────────
    def _fetch_batch_price_board(self, symbols: list[str]) -> bool:
        """
        1 request cho toàn bộ stocks: `Market().equity.quote(symbols)` (thế hệ 6).
        Trả về True nếu có ít nhất một tick.
        """
        if not symbols:
            return True
        try:
            from vnstock import Market
            ensure_api_key()
            df = Market().equity.quote(symbols)
        except Exception as e:  # VnstockError (nguồn/khoá/hạn mức/mạng) — luồng poll không được chết
            self.last_error = f"price_board: {str(e)[:100]}"
            return False
        if df is None or df.empty:
            return False
        return self._emit_board_rows(df) > 0

    def _emit_board_rows(self, df: pd.DataFrame, ticker: Optional[str] = None) -> int:
        """Dòng bảng giá thế hệ 6 (hồ sơ v5: `close_price`, `reference_price`, `high_price`,
        `low_price`, `total_volume`, `bid_price_N`/`bid_vol_N`…) → `_handle_tick`.

        `ticker` ép tên file quote (HĐTL: nguồn trả mã nội bộ 41I…, dashboard tìm VN30F1M).
        Trả số tick đã phát.
        """
        def _num(row, col):
            v = row.get(col)
            try:
                return None if v is None or pd.isna(v) else float(v)
            except (TypeError, ValueError):
                return None

        now_iso = datetime.now().isoformat(timespec="seconds")
        today = now_iso[:10]
        cols_list = [str(c).lower() for c in df.columns]
        df = df.set_axis(cols_list, axis=1)
        count = 0
        for _, row in df.iterrows():
            try:
                name = ticker or str(row.get("symbol") or "")
                name = name.upper()
                if not name or name == "NAN":
                    continue
                price = _num(row, "close_price")
                if price is None or price <= 0:
                    continue
                # `or 0` (bản cũ) GỘP hai ca khác hẳn nhau: "phiên chưa
                # khớp lệnh nào" và "bảng giá thiếu cột volume tick này".
                # Ca 2 làm baseline bị ghi đè = 0, nên tick KẾ TIẾP tính
                # delta = accum CẢ PHIÊN → volume bar phồng (audit 06/08,
                # cùng họ bug 78× trên AAA). Giữ None để phân biệt.
                accum_raw = _num(row, "total_volume")
                accum_volume = accum_raw if accum_raw is not None else 0
                ref = _num(row, "reference_price")
                high = _num(row, "high_price") or price
                low = _num(row, "low_price") or price

                # Convert accumulated → delta for bar aggregation.
                # First tick (no prior state, or new day): establish a
                # baseline with delta=0 rather than emitting the full
                # session-accumulated figure as one bogus bar. Daily
                # total is filled by the updater API, so missing the
                # pre-startup volume here is fine.
                if accum_raw is None:
                    # Thiếu số liệu tick này: KHÔNG đụng baseline (ghi 0 vào
                    # đó là mồi cho cú phồng ở tick sau), không cộng volume.
                    delta_volume = 0.0
                    accum_volume = self._last_accum_vol.get(name, 0)
                else:
                    delta_volume = accum_to_delta(
                        self._last_accum_vol.get(name),
                        self._last_accum_date.get(name),
                        accum_volume,
                        today,
                    )
                    self._last_accum_vol[name] = accum_volume
                    self._last_accum_date[name] = today

                # Bảng giá chỉ trả 3 mức L2 cho mọi instrument
                bids = _pick_depth_levels(row, cols_list, "bid", 3)
                asks = _pick_depth_levels(row, cols_list, "ask", 3)

                chg_pct = ((price - ref) / ref * 100) if ref else 0

                tick = {
                    "ticker": name,
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
                    "type": "futures" if is_futures(name) else "stock",
                }
                self._handle_tick(tick)
                count += 1
            except Exception as e:
                self.last_error = f"price_board row: {type(e).__name__}: {str(e)[:80]}"
                continue
        return count

    # ─────────────────────────────────────────────────────────────────────
    # Single-symbol fetchers (fallback)
    # ─────────────────────────────────────────────────────────────────────
    def _fetch_single_intraday(self, ticker: str):
        """Fallback per-stock: nến 1m (`_http_fetch_quote`) → _handle_tick."""
        try:
            tick = self._http_fetch_quote(ticker)
            if tick:
                self._handle_tick(tick)
        except Exception as e:
            self.last_error = f"poll {ticker}: {str(e)[:80]}"

    def _fetch_futures_quote(self, ticker: str) -> bool:
        """
        Bảng giá 1 HĐTL (VN30F1M…) qua `Market().futures(s).quote()` (thế hệ 6) — giá khớp,
        KL phiên, 3 bậc giá mua/bán — ghi `quote_<ticker>.json` như cổ phiếu.

        Thế hệ 6 KHÔNG có `volume_profile` cho HĐTL (dòng cũ: `Quote.price_depth()` của KBS
        trả KL khớp theo giá) ⇒ quote HĐTL không còn khối `volume_profile`.
        """
        try:
            from vnstock import Market
            ensure_api_key()
            df = Market().futures(ticker).quote()
        except Exception as e:  # VnstockError (nguồn/khoá/hạn mức/mạng) — luồng poll không được chết
            self.last_error = f"futures quote {ticker}: {str(e)[:80]}"
            return False
        if df is None or df.empty:
            self.last_error = f"futures quote {ticker}: empty result"
            return False
        return self._emit_board_rows(df.head(1), ticker=ticker) > 0

    def _fetch_index_quote(self, index_name: str):
        """
        Chỉ số (VNINDEX, VN30, ...) trong phiên qua `Market().index(s).quote()` (thế hệ 6);
        lỗi/rỗng ⇒ nến 1m của mặt tiền.
        """
        try:
            from vnstock import Market
            ensure_api_key()
            df = Market().index(index_name).quote()
        except Exception as e:  # VnstockError — rơi về nến 1m
            self.last_error = f"index quote {index_name}: {str(e)[:80]}"
            df = None
        try:
            if df is not None and not df.empty:
                # Hồ sơ v5 → tên `_emit_index_tick` đọc. %D tính từ giá tham chiếu (không đoán
                # đơn vị của `percent_change`: phân số hay phần trăm tuỳ hồ sơ).
                last = _index_quote_last_row(df)
                ref = pd.to_numeric(last.get("reference_price"), errors="coerce")
                close = pd.to_numeric(last.get("close"), errors="coerce")
                if pd.notna(ref) and ref > 0 and pd.notna(close):
                    last["chg_pct"] = round((close - ref) / ref * 100, 2)
                self._emit_index_tick(index_name, last)
                return
            tick = self._http_fetch_quote(index_name)
            if tick:
                self._handle_tick(tick)
        except Exception as e:
            self.last_error = f"poll {index_name}: {str(e)[:80]}"

    def _emit_index_tick(self, name: str, row):
        """Convert 1 row từ Market().index(s).quote() (đã đổi tên cột) → tick dict."""
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
        Fallback: bar 1m gần nhất trong 2 ngày qua mặt tiền `get_vnstock(t).quote.history`
        (thế hệ 6: `Market().equity|index(s).ohlcv`, giờ VN không múi).
        """
        from datetime import date, timedelta
        end = date.today().strftime("%Y-%m-%d")
        start = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
        try:
            from vnstock_auth import get_vnstock
            df = get_vnstock(ticker).quote.history(start=start, end=end, interval="1m")
        except Exception as e:  # VnstockError — chỗ gọi ghi tick khác hoặc bỏ lượt
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

        _ensure_live_dir()      # tạo lúc GHI, không phải lúc import
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
                        help="Run _fetch_futures_quote (use ALL for all futures)")
    parser.add_argument("--health-check", action="store_true",
                        help="Report live data + warehouse health")
    parser.add_argument("--duration", type=int, default=60, help="Test duration (s)")
    args = parser.parse_args()

    if args.health_check:
        _health_check()
        return

    if args.probe_profile:
        # Chạy _fetch_futures_quote cho 1 hoặc ALL futures
        client = get_wss_client()
        from vnstock_wss import FUTURES_SYMBOLS as _FS

        # Nếu argument là "ALL", probe tất cả futures
        targets = _FS if args.probe_profile.upper() == "ALL" else [args.probe_profile]

        for tkr in targets:
            print(f"\n{'─'*60}")
            print(f"[probe-profile] {tkr}")
            client.last_error = None
            ok = client._fetch_futures_quote(tkr)
            print(f"  Success: {ok}")
            print(f"  last_error: {client.last_error}")
            fpath = LIVE_DIR / f"quote_{tkr.upper()}.json"
            if fpath.exists():
                q = json.loads(fpath.read_text())
                print(f"  {fpath.name}: price {q.get('price')}, high {q.get('high')}, "
                      f"low {q.get('low')}, volume {q.get('volume')}")
                print(f"  bids: {q.get('bids')}  asks: {q.get('asks')}")
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
