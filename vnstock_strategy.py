"""
vnstock_strategy.py — Sandboxed strategy executor + backtest engine.

Architecture
------------
  StrategyExecutor (ABC)   — sandbox interface; run(code, df, params) -> dict
  InProcessExecutor        — AST whitelist + restricted exec + mp timeout (Option A)
  SubprocessExecutor       — placeholder for Option B (subprocess + cwd isolation)

  Backtest                 — apply signal() over historical OHLCV per ticker
  generate_strategy()      — ask an agent to draft a strategy
  improve_strategy()       — ask an agent to refine based on backtest metrics

Strategy contract
-----------------
  Generated code MUST define a single function:

      def signal(df: pd.DataFrame, params: dict) -> dict:
          # df has columns: time, open, high, low, close, volume (last N rows)
          # return: {"action": "buy"|"sell"|"hold",
          #          "entry": float, "tp": float, "sl": float,
          #          "confidence": 0..1}

Sandbox layers
--------------
  1. AST whitelist  — reject Import, eval/exec/open, dunder escapes
  2. Restricted globals — strip __builtins__, expose pd/np/math + safe builtins only
  3. multiprocessing timeout — kill if exceeds STRATEGY_TIMEOUT_S
  4. Output schema validation — reject if missing keys or wrong types
"""
from __future__ import annotations

import ast
import json
import math
import multiprocessing as mp
import os
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

import vnstock_memory as mem

# ── Constants ──────────────────────────────────────────────────────────────
STRATEGY_TIMEOUT_S = 10
DEFAULT_HORIZON_DAYS = 5
DEFAULT_BACKTEST_LOOKBACK_DAYS = 365
MIN_TRADES_TO_VALIDATE = 10

# ── AST whitelist ──────────────────────────────────────────────────────────
_FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "input", "exit", "quit", "help", "breakpoint",
    "memoryview", "id",
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__loader__", "__spec__",
    "__import__", "__getattribute__", "__setattr__",
}

_FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "shutil", "socket", "threading",
    "ctypes", "pickle", "marshal", "importlib", "pty", "shlex",
    "signal", "resource", "platform", "tempfile", "pathlib",
    "io", "fcntl", "mmap", "asyncio", "code", "codeop",
    "urllib", "requests", "http", "ftplib", "smtplib", "telnetlib",
}

_ALLOWED_DUNDERS = {"__init__", "__name__"}


class StrategyValidationError(ValueError):
    """Raised when strategy code fails AST whitelist or output contract."""


def _validate_ast(code: str) -> None:
    """Parse code and reject if any blacklisted construct appears."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise StrategyValidationError(f"SyntaxError: {e}") from e

    for node in ast.walk(tree):
        # No imports at all
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise StrategyValidationError("Import statements are not allowed")

        # No forbidden name access
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise StrategyValidationError(f"Forbidden name: {node.id}")

        # No dunder attribute access (except __init__/__name__ on user objects)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                if node.attr not in _ALLOWED_DUNDERS:
                    raise StrategyValidationError(
                        f"Forbidden dunder attribute: {node.attr}"
                    )

        # No file/IO function calls by name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_NAMES:
                raise StrategyValidationError(
                    f"Forbidden function call: {node.func.id}"
                )


def _safe_builtins() -> dict:
    safe_names = (
        "abs all any bool dict divmod enumerate filter float int isinstance "
        "issubclass len list map max min print range reversed round set "
        "slice sorted str sum tuple type zip True False None"
    ).split()
    real_builtins = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
    out = {n: real_builtins[n] for n in safe_names if n in real_builtins}
    out["__name__"] = "strategy_sandbox"
    return out


def _safe_globals(df: pd.DataFrame, params: dict) -> dict:
    return {
        "__builtins__": _safe_builtins(),
        "pd":     pd,
        "np":     np,
        "math":   math,
        "df":     df,
        "params": params,
    }


# ── Executor abstraction (clean swap A ↔ B) ────────────────────────────────
class StrategyExecutor(ABC):
    """Abstract sandbox runner. Swap implementations to harden security."""

    @abstractmethod
    def run(self, code: str, df: pd.DataFrame, params: dict) -> dict:
        """Execute strategy code and return signal() output. Raises on failure."""


def _signal_worker(code: str, df_pickle: bytes, params: dict, q: mp.Queue) -> None:
    """Subprocess target — runs in a forked process with restricted globals."""
    import pickle as _pkl
    try:
        df = _pkl.loads(df_pickle)
        _validate_ast(code)
        g = _safe_globals(df, params)
        l: dict = {}
        exec(compile(code, "<strategy>", "exec"), g, l)
        sig_fn = l.get("signal") or g.get("signal")
        if not callable(sig_fn):
            raise StrategyValidationError("Strategy must define `signal(df, params)`")
        result = sig_fn(df, params)
        if not isinstance(result, dict):
            raise StrategyValidationError("signal() must return a dict")
        q.put(("ok", result))
    except Exception as e:
        q.put(("err", f"{type(e).__name__}: {str(e)[:200]}"))


class InProcessExecutor(StrategyExecutor):
    """Option A: AST whitelist + restricted exec + multiprocessing timeout.

    `fast_mode=True` skips the mp.Process spawn (which costs ~0.5s/call on
    Windows). Code still runs through AST validation + restricted globals,
    so import/open/dunder escapes are blocked, but it loses the timeout
    isolation against infinite loops. Use only when running many backtest
    windows where the mp overhead dominates.
    """

    def __init__(self, timeout_s: float = STRATEGY_TIMEOUT_S,
                 fast_mode: bool = False):
        self.timeout_s = timeout_s
        self.fast_mode = fast_mode

    def run(self, code: str, df: pd.DataFrame, params: dict) -> dict:
        # Pre-flight AST validation in current process — cheap, fail-fast
        _validate_ast(code)

        if self.fast_mode:
            g = _safe_globals(df, params)
            l: dict = {}
            exec(compile(code, "<strategy>", "exec"), g, l)
            sig_fn = l.get("signal") or g.get("signal")
            if not callable(sig_fn):
                raise StrategyValidationError("Strategy must define `signal(df, params)`")
            result = sig_fn(df, params)
            if not isinstance(result, dict):
                raise StrategyValidationError("signal() must return a dict")
            return result

        import pickle as _pkl
        ctx = mp.get_context("spawn")
        q: mp.Queue = ctx.Queue()
        p = ctx.Process(
            target=_signal_worker,
            args=(code, _pkl.dumps(df), params, q),
        )
        p.start()
        p.join(timeout=self.timeout_s)
        if p.is_alive():
            p.terminate()
            p.join(2)
            if p.is_alive():
                p.kill()
            raise TimeoutError(f"Strategy exceeded {self.timeout_s}s timeout")
        if q.empty():
            raise RuntimeError("Strategy worker died without output")
        status, payload = q.get()
        if status == "err":
            raise RuntimeError(payload)
        return payload


# Default executor — swap to SubprocessExecutor when Option B lands
# fast_mode=True because mp.Process spawn on Windows costs ~0.5s per call,
# making 1000-window walk-forward backtest take ~10 minutes. AST whitelist
# + restricted globals still block file/network/import attacks.
EXECUTOR: StrategyExecutor = InProcessExecutor(fast_mode=True)

# Strict executor for one-off / production execution where isolation matters
# more than speed. Used by emit_recommendations() before publishing buy lists.
STRICT_EXECUTOR: StrategyExecutor = InProcessExecutor(fast_mode=False)


# ── Output schema validation ───────────────────────────────────────────────
def _validate_signal_output(out: dict) -> dict:
    """Coerce + validate the dict returned by signal()."""
    action = str(out.get("action", "hold")).lower()
    if action not in {"buy", "sell", "hold"}:
        action = "hold"

    def _f(k: str, default: float = 0.0) -> float:
        v = out.get(k, default)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "action":     action,
        "entry":      _f("entry"),
        "tp":         _f("tp"),
        "sl":         _f("sl"),
        "confidence": max(0.0, min(1.0, _f("confidence", 0.5))),
    }


# ── Backtest engine ────────────────────────────────────────────────────────
@dataclass
class BacktestConfig:
    universe:        list[str]
    lookback_days:   int = DEFAULT_BACKTEST_LOOKBACK_DAYS
    horizon_days:    int = DEFAULT_HORIZON_DAYS
    window_size:     int = 60
    step_days:       int = 5
    params:          dict = field(default_factory=dict)


def lite_config(universe: list[str]) -> "BacktestConfig":
    """Smaller config for UI-triggered training: 5 tickers, ~20 windows total.
    Runs in ~10-30s instead of 8 minutes. Use for smoke-testing the loop.
    """
    return BacktestConfig(
        universe=universe[:5],
        lookback_days=180,
        horizon_days=DEFAULT_HORIZON_DAYS,
        window_size=60,
        step_days=20,
    )


def _load_history(ticker: str, days: int) -> pd.DataFrame:
    """Lazy import of dashboard history loader to avoid Streamlit dep at module load."""
    try:
        from vnstock_dashboard import load_price_history
        return load_price_history(ticker, days=days)
    except Exception:
        return pd.DataFrame()


def _simulate_trade(future: pd.DataFrame, sig: dict) -> tuple[float, str]:
    """Walk forward the next N bars. Return (pnl_pct, reason)."""
    entry = sig["entry"]
    tp    = sig["tp"]
    sl    = sig["sl"]
    if entry <= 0 or future.empty:
        return 0.0, "no_data"
    last = float(future["close"].iloc[-1])

    # Long-only for now (action=buy). action=sell handled symmetrically.
    if sig["action"] == "buy":
        for _, bar in future.iterrows():
            hi, lo = float(bar["high"]), float(bar["low"])
            if sl > 0 and lo <= sl:
                return ((sl / entry) - 1) * 100, "sl"
            if tp > 0 and hi >= tp:
                return ((tp / entry) - 1) * 100, "tp"
        return ((last / entry) - 1) * 100, "expire"
    if sig["action"] == "sell":
        for _, bar in future.iterrows():
            hi, lo = float(bar["high"]), float(bar["low"])
            if sl > 0 and hi >= sl:
                return ((entry / sl) - 1) * 100, "sl"
            if tp > 0 and lo <= tp:
                return ((entry / tp) - 1) * 100, "tp"
        return ((entry / last) - 1) * 100, "expire"
    return 0.0, "hold"


def backtest(code: str, cfg: BacktestConfig) -> dict:
    """Walk-forward backtest. Returns metrics dict."""
    trades: list[dict] = []
    errors: list[str] = []

    for ticker in cfg.universe:
        hist = _load_history(ticker, days=cfg.lookback_days + cfg.horizon_days + 30)
        if hist.empty or len(hist) < cfg.window_size + cfg.horizon_days:
            continue
        # Walk forward in step_days increments
        max_start = len(hist) - cfg.window_size - cfg.horizon_days
        for i in range(0, max_start, cfg.step_days):
            window = hist.iloc[i:i + cfg.window_size].reset_index(drop=True)
            future = hist.iloc[i + cfg.window_size:
                               i + cfg.window_size + cfg.horizon_days].reset_index(drop=True)
            try:
                raw = EXECUTOR.run(code, window, cfg.params)
                sig = _validate_signal_output(raw)
            except Exception as e:
                errors.append(f"{ticker}@{i}: {type(e).__name__}: {str(e)[:80]}")
                continue
            if sig["action"] == "hold" or sig["entry"] <= 0:
                continue
            pnl, reason = _simulate_trade(future, sig)
            trades.append({
                "ticker":     ticker,
                "start_idx":  i,
                "action":     sig["action"],
                "pnl":        pnl,
                "reason":     reason,
                "confidence": sig["confidence"],
            })

    if not trades:
        return {
            "n_trades":      0,
            "win_rate":      None,
            "avg_return":    None,
            "sharpe":        None,
            "max_drawdown":  None,
            "expectancy":    None,
            "errors":        errors[:20],
        }

    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak)

    return {
        "n_trades":     int(len(trades)),
        "win_rate":     float(len(wins) / len(pnls)),
        "avg_return":   float(pnls.mean()),
        "sharpe":       float(pnls.mean() / pnls.std()) if pnls.std() > 0 else 0.0,
        "max_drawdown": float(dd.min()),
        "expectancy":   float(
            (len(wins) / len(pnls) * (wins.mean() if len(wins) else 0))
            + (len(losses) / len(pnls) * (losses.mean() if len(losses) else 0))
        ),
        "trades":       trades[:200],
        "errors":       errors[:20],
    }


# ── Strategy generation via agents ─────────────────────────────────────────
_STRATEGY_PROMPT = """\
Bạn là quant developer. Hãy viết MỘT chiến lược giao dịch ngắn hạn cho thị trường \
chứng khoán Việt Nam.

Output bắt buộc theo đúng format:

PARAMS:
{{"key1": value1, "key2": value2, ...}}

CODE:
def signal(df, params):
    ...

Yêu cầu nghiêm ngặt:
- Code dùng `params` thay cho hằng số magic — TẤT CẢ ngưỡng (RSI, MA period, stop %, take profit %) \
  đều đọc từ `params['xxx']` để có thể tune sau này
- Định nghĩa hàm: def signal(df, params) -> dict
- df có cột: time, open, high, low, close, volume (mới nhất ở cuối)
- Trả về dict: {{"action": "buy"|"sell"|"hold", "entry": float, "tp": float, "sl": float, "confidence": 0..1}}
- KHÔNG được dùng: import, open, exec, eval, file IO, network, os, sys
- Chỉ dùng: pd, np, math (có sẵn trong scope)
- entry/tp/sl là giá tuyệt đối (VND), không phải %
- Logic chạy được với window 60 ngày

QUAN TRỌNG — Tránh điều kiện tín hiệu mâu thuẫn:
- Ví dụ SAI: RSI < 30 (oversold → giá đang giảm) VÀ close > MA20 (giá trên MA) — hai điều kiện \
  hiếm khi xảy ra đồng thời → 0 trades
- Ví dụ ĐÚNG: RSI < 30 (oversold) VÀ RSI đang tăng lại (momentum reversal) → tín hiệu hợp lý
- Ví dụ ĐÚNG: close vừa cắt lên MA20 (golden cross) → breakout signal
- Chiến lược PHẢI sinh ra ít nhất 5-10 tín hiệu trên window 60 ngày với 5+ tickers VN30
- Dùng điều kiện ĐƠN GIẢN, 1-2 indicators, không stack quá nhiều AND

Bối cảnh hiện tại:
{context}

{prior_feedback}

Output đúng 2 phần: dòng `PARAMS:` + JSON dict, sau đó dòng `CODE:` + Python pure (không markdown wrapper).
"""

_TUNE_PROMPT = """\
Đây là CORE CODE đang chạy (KHÔNG được sửa, chỉ tune params):

```
{code}
```

Params HIỆN TẠI:
{current_params}

Backtest gần đây (cùng code, params hiện tại):
- n_trades: {n_trades}
- win_rate: {win_rate}
- avg_return: {avg_return}
- expectancy: {expectancy}
- max_drawdown: {max_drawdown}

Lịch sử params đã thử (nếu có):
{history}

Hãy đề xuất bộ params MỚI để cải thiện expectancy. Chỉ thay đổi giá trị, \
KHÔNG thêm/bớt key. KHÔNG sửa code.

Output BẮT BUỘC: chỉ MỘT dòng JSON dict, không markdown, không giải thích.
Ví dụ output: {{"rsi_period": 14, "rsi_oversold": 28, "stop_loss_pct": 2.5}}
"""

_REVISE_PROMPT = """\
CORE CODE hiện tại CẦN REVISE major ({revise_reason}):

```
{code}
```

Params đã tune nhiều lần, kết quả tốt nhất:
- expectancy: {expectancy}
- n_trades: {n_trades}
- win_rate: {win_rate}

Vấn đề chính (suy luận từ metrics):
{diagnosis}

Hãy VIẾT LẠI CORE CODE với cách tiếp cận khác (đổi indicator chính, đổi entry/exit logic, \
đổi market regime filter). Có thể giữ structure dùng `params` cho tunability.

QUAN TRỌNG — Tránh lỗi phổ biến gây 0 trades:
- KHÔNG stack quá nhiều điều kiện AND — mỗi điều kiện bổ sung làm giảm số tín hiệu theo hàm mũ
- KHÔNG dùng điều kiện mâu thuẫn: RSI<30 (oversold/giảm) VÀ close>MA (đang trên MA) — hiếm gặp
- PHẢI sinh ít nhất 5-10 tín hiệu buy/sell trên window 60 ngày với dữ liệu VN30
- Dùng 1-2 indicators đơn giản: MA crossover, RSI threshold đơn, volume breakout, hoặc Bollinger

Output cùng format như khi tạo mới:
PARAMS:
{{...}}

CODE:
def signal(df, params):
    ...
"""

_IMPROVEMENT_PROMPT = """\
Đây là chiến lược trước:

```
{code}
```

Backtest results:
- n_trades: {n_trades}
- win_rate: {win_rate}
- avg_return: {avg_return}
- sharpe: {sharpe}
- max_drawdown: {max_drawdown}
- expectancy: {expectancy}

Sample errors (nếu có):
{errors}

Hãy CẢI THIỆN chiến lược này. Giữ nguyên contract `def signal(df, params) -> dict`.
Có thể thay đổi indicator, ngưỡng, position sizing, exit logic.
{constraints}

Output: chỉ Python code mới, KHÔNG markdown wrapper.
"""


def _strip_code_fences(text: str) -> str:
    """Remove ```python ... ``` or ``` ... ``` wrappers if present."""
    t = text.strip()
    if t.startswith("```"):
        # remove first line (```python or ```)
        nl = t.find("\n")
        if nl > 0:
            t = t[nl + 1:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _parse_params_and_code(text: str) -> tuple[dict, str]:
    """Split the agent output into (params_dict, code_str).

    Expected format:
        PARAMS:
        {"key": value, ...}

        CODE:
        def signal(df, params):
            ...
    """
    t = text.strip()
    params: dict = {}
    code = t
    if "PARAMS:" in t and "CODE:" in t:
        try:
            params_part = t.split("PARAMS:", 1)[1].split("CODE:", 1)[0].strip()
            code_part = t.split("CODE:", 1)[1].strip()
            params_part = _strip_code_fences(params_part)
            params = json.loads(params_part)
            if not isinstance(params, dict):
                params = {}
            code = _strip_code_fences(code_part)
        except Exception:
            code = _strip_code_fences(t)
    else:
        code = _strip_code_fences(t)
    return params, code


def generate_strategy(
    agent,
    context_summary: str = "",
    prior_feedback: str = "",
) -> tuple[str, dict, str | None]:
    """Ask an agent to generate a fresh strategy. Returns (code, params, error)."""
    prompt = _STRATEGY_PROMPT.format(
        context=context_summary or "Thị trường VN, large-cap, daily timeframe.",
        prior_feedback=prior_feedback or "(không có feedback ưu tiên)",
    )
    text, err = agent.generate(prompt, max_tokens=2000)
    if err:
        return "", {}, err
    params, code = _parse_params_and_code(text)
    try:
        _validate_ast(code)
    except StrategyValidationError as e:
        return code, params, f"AST rejected: {e}"
    if "def signal" not in code:
        return code, params, "Missing `def signal()` definition"
    return code, params, None


def tune_params(
    agent,
    code: str,
    current_params: dict,
    metrics: dict,
    history: list[dict] | None = None,
) -> tuple[dict, str | None]:
    """Ask an agent to suggest new params (JSON only). Code is NOT changed.
    Returns (new_params, error). Empty dict on failure.
    """
    hist_str = "(không có)"
    if history:
        hist_str = "\n".join(
            f"- {h.get('params')} → expectancy={h.get('expectancy')}"
            for h in history[:5]
        )
    prompt = _TUNE_PROMPT.format(
        code=code,
        current_params=json.dumps(current_params, ensure_ascii=False),
        n_trades=metrics.get("n_trades", 0),
        win_rate=metrics.get("win_rate"),
        avg_return=metrics.get("avg_return"),
        expectancy=metrics.get("expectancy"),
        max_drawdown=metrics.get("max_drawdown"),
        history=hist_str,
    )
    text, err = agent.generate(prompt, max_tokens=400)
    if err:
        return {}, err
    raw = _strip_code_fences(text).strip()
    # Find first { ... } block — agents sometimes still add prose
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}, "No JSON dict found in tune output"
    try:
        new_params = json.loads(raw[start:end + 1])
        if not isinstance(new_params, dict):
            return {}, "Tune output is not a dict"
        # Defensive: only keep keys that exist in current_params
        new_params = {k: v for k, v in new_params.items() if k in current_params}
        if not new_params:
            return {}, "Tune output had no overlapping keys"
        # Merge with current to preserve untouched keys
        merged = {**current_params, **new_params}
        return merged, None
    except json.JSONDecodeError as e:
        return {}, f"JSON parse error: {e}"


def revise_strategy(
    agent,
    code: str,
    metrics: dict,
    diagnosis: str = "",
    revise_reason: str = "hiệu quả thấp",
) -> tuple[str, dict, str | None]:
    """Ask an agent to write a new core (different approach). Returns (code, params, err)."""
    prompt = _REVISE_PROMPT.format(
        code=code,
        revise_reason=revise_reason,
        n_trades=metrics.get("n_trades", 0),
        win_rate=metrics.get("win_rate"),
        expectancy=metrics.get("expectancy"),
        diagnosis=diagnosis or "Expectancy âm hoặc số trade thấp — cần đổi cách tiếp cận.",
    )
    text, err = agent.generate(prompt, max_tokens=2000)
    if err:
        return "", {}, err
    params, new_code = _parse_params_and_code(text)
    try:
        _validate_ast(new_code)
    except StrategyValidationError as e:
        return new_code, params, f"AST rejected: {e}"
    if "def signal" not in new_code:
        return new_code, params, "Missing `def signal()` definition"
    return new_code, params, None


def improve_strategy(
    agent,
    code: str,
    metrics: dict,
    constraints: str = "",
) -> tuple[str, str | None]:
    prompt = _IMPROVEMENT_PROMPT.format(
        code=code,
        n_trades=metrics.get("n_trades", 0),
        win_rate=metrics.get("win_rate"),
        avg_return=metrics.get("avg_return"),
        sharpe=metrics.get("sharpe"),
        max_drawdown=metrics.get("max_drawdown"),
        expectancy=metrics.get("expectancy"),
        errors="\n".join(metrics.get("errors", [])[:5]) or "(none)",
        constraints=constraints,
    )
    text, err = agent.generate(prompt, max_tokens=1500)
    if err:
        return "", err
    new_code = _strip_code_fences(text)
    try:
        _validate_ast(new_code)
    except StrategyValidationError as e:
        return new_code, f"AST rejected: {e}"
    return new_code, None


# ── End-to-end pipeline used by train loop ─────────────────────────────────
import uuid as _uuid
from datetime import datetime as _dt, timedelta as _td

# ── Maturity heuristics ────────────────────────────────────────────────────
WEEKLY_REVISE_DAYS     = 7
N_STABLE_WEEKS_REQUIRED = 3
N_DEGRADE_PERIODS      = 3   # consecutive negative-expectancy tunes → reopen revise


def _is_degraded(family_id: str) -> bool:
    """True if the last N_DEGRADE_PERIODS backtests all had expectancy ≤ 0.

    Used to detect when a once-stable core has stopped working (regime change,
    data drift, etc.) so the system can reopen revision even after stabilisation.
    """
    hist = mem.family_history(family_id, limit=N_DEGRADE_PERIODS)
    if len(hist) < N_DEGRADE_PERIODS:
        return False  # not enough history to judge
    return all((h.get("expectancy") or 0) <= 0 for h in hist[:N_DEGRADE_PERIODS])


def _should_revise(active: dict) -> bool:
    """True if it's time to revise (rewrite core), False if just tune params.

    Rules (in priority order):
      1. No active strategy          → revise (cold start, handled by caller)
      2. 0 trades in latest backtest → revise immediately (broken signal logic)
      3. is_core_stable=1 BUT last N tunes all negative → degrade detected,
         unmark stable and revise
      4. is_core_stable=1 and still healthy → only tune, never revise
      5. Last revise > WEEKLY_REVISE_DAYS ago → weekly revise cadence
    """
    if not active:
        return True

    fam = active.get("family_id")

    # Rule 2: 0 trades → broken code, revise immediately
    if fam:
        hist = mem.family_history(fam, limit=1)
        if hist and (hist[0].get("n_trades") or 0) == 0:
            return True

    # Rules 3 & 4: stable core
    if active.get("is_core_stable"):
        if fam and _is_degraded(fam):
            # Performance has deteriorated — reopen revision cycle
            mem.mark_core_stable(active["id"], stable=False)
            return True
        return False  # healthy stable core → tune only

    # Rule 5: weekly cadence for unstable core
    try:
        last_revise = _dt.fromisoformat(active.get("created_at", ""))
    except Exception:
        return True
    return (_dt.now() - last_revise).days >= WEEKLY_REVISE_DAYS


def _check_stability(family_id: str) -> bool:
    """Mark core stable if the last N revisions all had positive expectancy."""
    history = mem.family_history(family_id, limit=N_STABLE_WEEKS_REQUIRED + 1)
    if len(history) < N_STABLE_WEEKS_REQUIRED:
        return False
    revisions = [h for h in history if h.get("status") in ("active", "validated", "retired")]
    revisions = revisions[:N_STABLE_WEEKS_REQUIRED]
    if len(revisions) < N_STABLE_WEEKS_REQUIRED:
        return False
    for h in revisions:
        if (h.get("expectancy") or -999) <= 0 \
           or (h.get("n_trades") or 0) < MIN_TRADES_TO_VALIDATE:
            return False
    return True


def _do_backtest(code: str, params: dict, cfg: BacktestConfig) -> tuple[dict, str, str]:
    """Run backtest and return (metrics, period_start, period_end)."""
    cfg.params = params
    metrics = backtest(code, cfg)
    period_start = (pd.Timestamp.now() - pd.Timedelta(days=cfg.lookback_days)).date().isoformat()
    period_end   = pd.Timestamp.now().date().isoformat()
    return metrics, period_start, period_end


def _cold_start(
    agent, universe, context_summary, cfg, extra_agents: list | None = None
) -> tuple[Optional[int], dict]:
    """Generate fresh strategy with competition — all agents write independently, best wins."""
    all_agents = [agent] + (extra_agents or [])
    seen: set[str] = set()
    unique_agents: list = []
    for a in all_agents:
        if getattr(a, "is_available", True) and a.name not in seen:
            unique_agents.append(a)
            seen.add(a.name)

    # Each agent independently generates a fresh strategy
    candidates: list[tuple[str, str, dict, dict, str, str]] = []
    for ag in unique_agents:
        code, params, err = generate_strategy(ag, context_summary=context_summary)
        if err and not code:
            continue
        metrics, ps, pe = _do_backtest(code, params, cfg)
        candidates.append((ag.name, code, params, metrics, ps, pe))

    if not candidates:
        return None, {"error": "no agent produced valid strategy on cold-start"}

    # Pick best by expectancy; fallback to most trades if all expectancy ≤ 0
    best = max(candidates, key=lambda c: (
        c[3].get("expectancy") or -999,
        c[3].get("n_trades") or 0,
    ))
    best_agent, code, params, metrics, ps, pe = best

    family = _uuid.uuid4().hex[:8]
    competitors = [c[0] for c in candidates]
    sid = mem.save_strategy(
        agent_name=best_agent,
        name=(
            f"family-{family} v1 by {best_agent}"
            + (f" (vs {len(candidates)} agents)" if len(candidates) > 1 else "")
        ),
        code=code,
        params=params,
        description=f"Cold-start competition ({', '.join(competitors)})",
        status="draft",
        family_id=family,
    )
    mem.save_backtest(sid, ps, pe, ",".join(universe[:10]), metrics)
    if metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
       and (metrics.get("expectancy") or -999) > 0:
        mem.promote_strategy(sid, retire_others=True)
    else:
        mem.update_strategy_status(sid, "validated"
                                   if metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE
                                   else "draft")
        mem.promote_strategy(sid, retire_others=True)  # always have one active
    return sid, {**metrics, "cold_start_winner": best_agent, "cold_start_competitors": competitors}


def _do_revise(
    agent, active, cfg, extra_agents: list | None = None
) -> tuple[Optional[int], dict]:
    """Rewrite core with competition — ALL agents write independently, best wins.

    Each available agent generates a completely new strategy. All are backtested.
    The one with highest expectancy is adopted (if better than current).
    This gives genuine code diversity — not just param variations.
    """
    code        = active["code"]
    family      = active.get("family_id") or _uuid.uuid4().hex[:8]
    cur_metrics = mem.latest_backtest(active["id"]) or {}

    # Build the diagnosis context once (shared across all agents)
    was_stable = bool(active.get("is_core_stable"))
    nt  = cur_metrics.get("n_trades") or 0
    exp = cur_metrics.get("expectancy") or 0
    if nt == 0:
        revise_reason = "0 trades — điều kiện signal không bao giờ trigger"
        diagnosis = "Strategy không sinh ra tín hiệu nào. Điều kiện entry quá khắt khe hoặc mâu thuẫn."
    elif was_stable and _is_degraded(family):
        revise_reason = (
            f"degradation sau khi ổn định — {N_DEGRADE_PERIODS} kỳ liên tiếp expectancy ≤ 0 "
            f"(gần nhất: {exp:.3f})"
        )
        diagnosis = (
            "Core đã từng ổn định nhưng hiệu quả suy giảm liên tục. "
            "Khả năng market regime đã thay đổi. Cần đổi logic hoàn toàn."
        )
    else:
        revise_reason = f"weekly revise — expectancy={exp:.3f}, n_trades={nt}"
        diagnosis = "Expectancy âm hoặc số trade thấp — cần đổi cách tiếp cận."

    # All agents compete — de-dup by name
    all_agents = [agent] + (extra_agents or [])
    seen: set[str] = set()
    unique_agents = []
    for a in all_agents:
        if a.is_available and a.name not in seen:
            unique_agents.append(a)
            seen.add(a.name)

    # Each agent generates its own new code independently
    candidates: list[tuple[str, str, dict, dict, str, str]] = []
    for ag in unique_agents:
        new_code, new_params, err = revise_strategy(
            ag, code, cur_metrics,
            diagnosis=diagnosis, revise_reason=revise_reason,
        )
        if err and not new_code:
            continue
        metrics, ps, pe = _do_backtest(new_code, new_params, cfg)
        candidates.append((ag.name, new_code, new_params, metrics, ps, pe))

    if not candidates:
        return None, {"error": "no valid revision from any agent"}

    # Competition: pick the candidate with highest expectancy
    best = max(candidates, key=lambda c: c[3].get("expectancy") or -999)
    best_agent, best_code, best_params, best_metrics, best_ps, best_pe = best
    competitors = [c[0] for c in candidates]

    sid = mem.save_strategy(
        agent_name=best_agent,
        name=(
            f"family-{family} revise by {best_agent} @ {time.strftime('%m-%d')}"
            + (f" (vs {len(candidates)} agents)" if len(candidates) > 1 else "")
        ),
        code=best_code,
        params=best_params,
        description=f"Revise competition ({', '.join(competitors)}): {revise_reason}",
        parent_id=active["id"],
        status="draft",
        family_id=family,
    )
    mem.save_backtest(sid, best_ps, best_pe, ",".join(cfg.universe[:10]), best_metrics)

    cur_exp = cur_metrics.get("expectancy") or -999
    new_exp = best_metrics.get("expectancy") or -999
    if new_exp > cur_exp and best_metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE:
        mem.promote_strategy(sid, retire_others=True)
        if _check_stability(family):
            mem.mark_core_stable(sid, True)
    else:
        mem.update_strategy_status(sid, "retired")

    return sid, {**best_metrics, "revise_winner": best_agent, "revise_competitors": competitors}


def _do_tune(agents: list, active: dict, cfg: BacktestConfig) -> tuple[Optional[int], dict]:
    """Daily-cadence: each agent suggests new params, run backtest, adopt best."""
    code = active["code"]
    try:
        cur_params = json.loads(active.get("params_json") or "{}")
    except Exception:
        cur_params = {}
    cur_metrics = mem.latest_backtest(active["id"]) or {}
    if not cur_params:
        return active["id"], {"error": "active strategy has no params to tune"}

    candidates: list[tuple[str, dict, dict]] = []
    for ag in agents:
        if not ag.is_available:
            continue
        new_params, err = tune_params(ag, code, cur_params, cur_metrics)
        if err or not new_params:
            continue
        metrics, _, _ = _do_backtest(code, new_params, cfg)
        candidates.append((ag.name, new_params, metrics))

    if not candidates:
        return active["id"], {"error": "no agent produced valid tune"}

    name, new_params, new_metrics = max(
        candidates,
        key=lambda c: c[2].get("expectancy") or -999,
    )
    cur_exp = cur_metrics.get("expectancy") or -999
    new_exp = new_metrics.get("expectancy") or -999

    if new_exp > cur_exp:
        mem.update_strategy_params(active["id"], new_params, name)
        mem.save_backtest(
            active["id"],
            (pd.Timestamp.now() - pd.Timedelta(days=cfg.lookback_days)).date().isoformat(),
            pd.Timestamp.now().date().isoformat(),
            ",".join(cfg.universe[:10]),
            new_metrics,
        )
        return active["id"], {**new_metrics, "tuned_by": name}
    return active["id"], {"error": "no candidate improved expectancy"}


def develop_and_backtest(
    agent,
    universe: list[str],
    context_summary: str = "",
    n_iterations: int = 2,  # legacy arg, unused in new flow
    cfg: Optional[BacktestConfig] = None,
    mode: str = "auto",
    extra_agents: list | None = None,
) -> tuple[Optional[int], dict]:
    """Develop / tune / revise the active strategy. Adaptive cadence.

    Modes:
      auto    — choose tune vs revise based on age + stability flag (default)
      tune    — force daily tune (params only); cold-start if no active
      revise  — force weekly revise (rewrite core)
      fresh   — force cold start (ignore existing active, retire it)

    All enabled agents share one family. `agent` is the lead; `extra_agents`
    additional agents that participate in the daily tune competition.
    """
    if cfg is None:
        cfg = BacktestConfig(universe=universe)
    cfg.universe = universe  # ensure consistency

    active = mem.get_active_family()

    if mode == "fresh" or active is None:
        return _cold_start(agent, universe, context_summary, cfg, extra_agents=extra_agents)

    if mode == "revise" or (mode == "auto" and _should_revise(active)):
        return _do_revise(agent, active, cfg, extra_agents=extra_agents)

    # tune mode (or auto + not yet time to revise)
    pool = [agent] + (extra_agents or [])
    # de-dup by name
    seen: set[str] = set()
    unique = []
    for a in pool:
        if a.name not in seen:
            unique.append(a)
            seen.add(a.name)
    return _do_tune(unique, active, cfg)


# ── Convert latest signal of best strategy → recommendation ────────────────
def emit_recommendations(
    universe: list[str],
    max_recs: int = 5,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    brief_id: Optional[int] = None,
    min_avg_volume: int = 100_000,
) -> list[dict]:
    """Run best-validated strategy on most-recent window per ticker;
    return + persist actionable recs.

    min_avg_volume: skip tickers whose 30-day avg daily volume is below this
    threshold (default 100,000 shares) — illiquid stocks can't fill orders
    reliably at the signal price.

    Returns list of rec dicts. The last element (if list non-empty) may be
    replaced by a '_stats' sentinel — callers should ignore dicts without 'ticker'.
    Stats are always appended as the final element regardless of recs count.
    """
    bests = mem.best_strategies(limit=3)
    if not bests:
        return [{"_stats": True, "reason": "no_validated_strategy",
                 "n_scanned": 0, "n_no_data": 0, "n_low_vol": 0,
                 "n_executed": 0, "n_hold": 0, "n_buy": 0,
                 "n_errors": 0, "errors_sample": []}]

    stats = {"_stats": True, "n_scanned": len(universe),
             "n_no_data": 0, "n_low_vol": 0, "n_executed": 0,
             "n_hold": 0, "n_buy": 0, "n_errors": 0}
    # Capture up to 5 distinct error signatures so the UI can surface them.
    # Without this, a strategy that throws on every ticker leaves 0 recs and
    # 0 visible diagnostics — see fail-silent issue in the scan UI.
    errors_seen: dict[str, str] = {}
    recs: list[dict] = []
    for s in bests:
        code = s["code"]
        for ticker in universe:
            if len(recs) >= max_recs:
                break
            hist = _load_history(ticker, days=120)
            if hist.empty or len(hist) < 60:
                stats["n_no_data"] += 1
                continue
            if hist["volume"].tail(30).mean() < min_avg_volume:
                stats["n_low_vol"] += 1
                continue
            window = hist.tail(60).reset_index(drop=True)
            try:
                raw = STRICT_EXECUTOR.run(code, window, {})
                sig = _validate_signal_output(raw)
                stats["n_executed"] += 1
            except Exception as e:
                stats["n_errors"] += 1
                msg = f"{type(e).__name__}: {str(e)[:160]}"
                if msg not in errors_seen and len(errors_seen) < 5:
                    errors_seen[msg] = ticker
                continue
            if sig["action"] != "buy" or sig["entry"] <= 0:
                stats["n_hold"] += 1
                continue
            stats["n_buy"] += 1
            rec_id = mem.save_recommendation(
                ticker=ticker,
                action=sig["action"],
                entry=sig["entry"],
                tp=sig["tp"],
                sl=sig["sl"],
                rationale=f"Strategy #{s['id']} ({s['name']}), conf={sig['confidence']:.2f}",
                horizon_days=horizon_days,
                brief_id=brief_id,
                strategy_id=s["id"],
            )
            recs.append({
                "id":       rec_id,
                "ticker":   ticker,
                "entry":    sig["entry"],
                "tp":       sig["tp"],
                "sl":       sig["sl"],
                "rationale": f"Strategy #{s['id']}",
                "strategy": s["name"],
            })
        if len(recs) >= max_recs:
            break
    stats["errors_sample"] = [
        {"error": msg, "example_ticker": tk} for msg, tk in errors_seen.items()
    ]
    return recs + [stats]


# ── Per-ticker AI recommendation ───────────────────────────────────────────
_TICKER_VOTE_PROMPT = """\
Bạn là chuyên gia phân tích kỹ thuật độc lập cho thị trường Việt Nam.

Ticker: {ticker}
Chỉ số kỹ thuật:
  Giá đóng cửa : {close:,.0f} VND
  RSI(14)      : {rsi:.1f}  ({rsi_desc})
  MA20         : {ma20:,.0f} ({vs_ma20_desc} {vs_ma20_pct:+.1f}%)
  Volume/TB20  : {vol_ratio:.1f}x
  Xu hướng 5N  : {trend_5d:+.1f}%

Chiến lược AI đang gợi ý: {action_upper}
  Entry: {entry_str}  |  TP: {tp_str}  |  SL: {sl_str}

Dựa trên phân tích kỹ thuật CỦA BẠN, trả lời CHÍNH XÁC theo format sau (không thêm text khác):
ĐÁNH GIÁ: MUA|BÁN|KHÔNG GIAO DỊCH
ĐỒNG Ý VỚI STRATEGY: CÓ|KHÔNG
LÝ DO: [1-2 câu ngắn gọn]
"""

_TICKER_ANALYSIS_PROMPT = """\
Bạn là chuyên gia phân tích kỹ thuật cổ phiếu Việt Nam.

Ticker: {ticker} — Ngày phân tích: {date}

=== DỮ LIỆU KỸ THUẬT ===
Giá hiện tại : {close:>12,.0f} VND
RSI(14)      : {rsi:>10.1f}  ({rsi_desc})
MA20         : {ma20:>12,.0f} VND  | Giá đang {vs_ma20_desc} MA20 ({vs_ma20_pct:+.1f}%)
Volume/TB20  : {vol_ratio:>10.1f}x
Xu hướng 5N  : {trend_5d:>10.1f}%
52W High/Low : {high_52w:,.0f} / {low_52w:,.0f} VND

=== TÍN HIỆU TỪ AI STRATEGY ===
Chiến lược   : {strategy_name}
Hành động    : {action_upper}
Confidence   : {confidence:.0%}
Entry gợi ý  : {entry_str}
Take Profit  : {tp_str} ({tp_pct})
Cut Loss     : {sl_str} ({sl_pct})
Risk/Reward  : 1:{rr}
{news_block}
Viết khuyến nghị đầu tư CHI TIẾT bằng tiếng Việt theo đúng cấu trúc (dùng **bold** cho tiêu đề):

**Quyết định:** MUA / BÁN / KHÔNG GIAO DỊCH — nêu mức giá cụ thể.

**Giá vào lệnh:** Giá cụ thể và lý do chọn mức giá này (vùng hỗ trợ, MA, Fibonacci…).

**Giá chốt lời (Take Profit):** Giá cụ thể, lý do (kháng cự, mục tiêu kỹ thuật…).

**Giá cắt lỗ (Cut Loss):** Giá cụ thể, lý do (phá hỗ trợ, invalidation level…).

**Lý do kỹ thuật:** 2-3 câu phân tích dựa trên RSI, MA, volume, xu hướng ở trên.

**Tin tức ảnh hưởng:** Nếu có tin tức liên quan trong phần "TIN TỨC" ở trên thì BẮT BUỘC nêu tên tiêu đề tin và giải thích tác động cụ thể (hỗ trợ/cản trở quyết định mua/bán như thế nào). Nếu không có tin tức thì ghi "Không có tin tức mới".

**Rủi ro cần lưu ý:** 1-2 điều kiện cụ thể khiến phải thay đổi quyết định.

Yêu cầu: dùng số liệu cụ thể từ bảng trên, ngắn gọn súc tích, không vòng vo.
"""


def _ticker_indicators(df: pd.DataFrame) -> dict:
    """Compute RSI, MA, volume ratio, trend from OHLCV df (no external deps)."""
    close = df["close"].astype(float)
    n = len(close)

    # RSI(14) via EWM
    rsi = 50.0
    if n >= 15:
        delta = close.diff(1)
        roll_up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        roll_dn = (-delta).clip(lower=0).ewm(com=13, adjust=False).mean()
        rs = roll_up / roll_dn.replace(0, float("nan"))
        val = 100.0 - (100.0 / (1.0 + rs))
        v = val.iloc[-1]
        rsi = float(v) if not (math.isnan(v) if isinstance(v, float) else False) else 50.0

    ma20 = float(close.rolling(20).mean().iloc[-1]) if n >= 20 else float(close.iloc[-1])

    vol = df.get("volume", None) if hasattr(df, "get") else None
    if vol is None and "volume" in df.columns:
        vol = df["volume"].astype(float)
    vol_ratio = 1.0
    if vol is not None and len(vol) >= 20:
        avg20 = float(vol.rolling(20).mean().iloc[-1]) or 1.0
        vol_ratio = float(vol.iloc[-1]) / avg20

    trend_5d = 0.0
    if n >= 6:
        trend_5d = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100

    n252 = min(n, 252)
    return {
        "close":    float(close.iloc[-1]),
        "rsi":      rsi,
        "ma20":     ma20,
        "vol_ratio": vol_ratio,
        "trend_5d": trend_5d,
        "high_52w": float(close.tail(n252).max()),
        "low_52w":  float(close.tail(n252).min()),
    }


def analyze_ticker(
    agent,
    ticker: str,
    df: pd.DataFrame,
) -> dict:
    """Run active strategy signal on one ticker + generate AI explanation.

    Returns dict:
      action, entry, tp, sl, confidence, explanation,
      strategy_name, strategy_id, indicators
    """
    from datetime import date as _date_cls

    active = mem.get_active_family()
    if not active:
        return {
            "action": "hold", "entry": None, "tp": None, "sl": None,
            "confidence": 0,
            "explanation": (
                "⚠️ Chưa có chiến lược AI nào được huấn luyện. "
                "Vào tab **Thị trường → Chiến lược & khuyến nghị** → nhấn "
                "**Lite training** để bắt đầu."
            ),
            "strategy_name": None, "strategy_id": None, "indicators": {},
        }

    code = active.get("code") or ""
    try:
        params = json.loads(active.get("params_json") or "{}")
    except Exception:
        params = {}

    indic = _ticker_indicators(df)
    close = indic["close"]

    # Run signal
    sig: dict = {"action": "hold", "entry": close, "tp": None, "sl": None, "confidence": 0.0}
    if code:
        try:
            raw = EXECUTOR.run(code, df.tail(120).reset_index(drop=True), params)
            sig = _validate_signal_output(raw)
        except Exception as exc:
            sig["_run_error"] = str(exc)

    action = sig.get("action", "hold")
    entry  = sig.get("entry") or close
    tp     = sig.get("tp") or None
    sl     = sig.get("sl") or None
    conf   = sig.get("confidence") or 0.0

    def _price_str(v: Optional[float], ref: float) -> tuple[str, str]:
        if not v or v <= 0:
            return "—", ""
        pct = (v / ref - 1) * 100
        return f"{v:,.0f} VND", f"{pct:+.1f}%"

    tp_str, tp_pct = _price_str(tp, entry)
    sl_str, sl_pct = _price_str(sl, entry)
    rr = "—"
    if tp and sl and entry and abs(entry - sl) > 0:
        rr = f"{abs((tp - entry) / (entry - sl)):.1f}"

    rsi = indic["rsi"]
    rsi_desc = "quá mua" if rsi > 70 else ("quá bán" if rsi < 30 else "trung tính")
    vs_ma20_pct = (close / indic["ma20"] - 1) * 100 if indic["ma20"] else 0
    vs_ma20_desc = "trên" if vs_ma20_pct >= 0 else "dưới"
    action_upper = {"buy": "MUA 🟢", "sell": "BÁN 🔴"}.get(action, "KHÔNG GIAO DỊCH 🟡")

    # Fetch per-ticker news context (best-effort, silent on failure)
    _news_section = ""
    try:
        from vnstock_news import news_for_ticker as _nft
        _ticker_news = _nft(ticker)
        if _ticker_news:
            _lines = ["\n=== TIN TỨC GẦN ĐÂY ==="]
            for _n in _ticker_news[:5]:
                _title   = (_n.get("news_title") or "").strip()
                _summary = (_n.get("news_short_content") or _n.get("news_sub_title") or "").strip()
                _date_s  = _n.get("_date_sort", "")[:10]
                if _title:
                    _lines.append(f"• [{_date_s}] {_title}")
                    if _summary:
                        _lines.append(f"  {_summary[:200]}")
            _news_section = "\n".join(_lines) + "\n"
    except Exception:
        pass

    prompt = _TICKER_ANALYSIS_PROMPT.format(
        ticker=ticker,
        date=_date_cls.today().isoformat(),
        close=close,
        rsi=rsi, rsi_desc=rsi_desc,
        ma20=indic["ma20"], vs_ma20_desc=vs_ma20_desc, vs_ma20_pct=vs_ma20_pct,
        vol_ratio=indic["vol_ratio"],
        trend_5d=indic["trend_5d"],
        high_52w=indic["high_52w"], low_52w=indic["low_52w"],
        strategy_name=active["name"],
        action_upper=action_upper, confidence=conf,
        entry_str=f"{entry:,.0f} VND" if entry else "—",
        tp_str=tp_str, tp_pct=tp_pct,
        sl_str=sl_str, sl_pct=sl_pct, rr=rr,
        news_block=_news_section,
    )

    explanation = ""
    if agent and getattr(agent, "is_available", False):
        text, err = agent.generate(prompt, max_tokens=500)
        explanation = text or (f"Lỗi AI: {err}" if err else "")
    else:
        explanation = "Không có AI agent khả dụng — kiểm tra API key trong `.env`."

    return {
        "action":        action,
        "entry":         entry,
        "tp":            tp,
        "sl":            sl,
        "confidence":    conf,
        "explanation":   explanation,
        "strategy_name": active["name"],
        "strategy_id":   active["id"],
        "indicators":    indic,
    }


def analyze_ticker_consensus(
    agents: list,
    ticker: str,
    df: pd.DataFrame,
) -> dict:
    """Multi-agent consensus for a single ticker.

    Flow:
      1. Run strategy signal once (deterministic — same code, same data for all)
      2. Each agent votes independently: agree/disagree + own action assessment
      3. Compute consensus: majority vote + agreement-with-strategy rate
      4. Lead agent writes the full explanation
    Returns a dict with keys:
      action (strategy signal), consensus_action, agreement_rate,
      strategy_agree_rate, votes (per-agent), entry, tp, sl,
      explanation (lead agent), n_agents
    """
    from collections import Counter

    active = mem.get_active_family()
    if not active:
        return {
            "error": "no_active_strategy",
            "explanation": (
                "⚠️ Chưa có chiến lược AI nào. "
                "Vào tab Thị trường → Chiến lược & khuyến nghị → Lite training."
            ),
        }

    code = active.get("code") or ""
    try:
        params = json.loads(active.get("params_json") or "{}")
    except Exception:
        params = {}

    indic = _ticker_indicators(df)
    close = indic["close"]

    # Step 1: deterministic signal (same for every agent)
    sig: dict = {"action": "hold", "entry": close, "tp": None, "sl": None, "confidence": 0.0}
    if code:
        try:
            raw = EXECUTOR.run(code, df.tail(120).reset_index(drop=True), params)
            sig = _validate_signal_output(raw)
        except Exception as exc:
            sig["_run_error"] = str(exc)

    action = sig.get("action", "hold")
    entry  = sig.get("entry") or close
    tp     = sig.get("tp") or None
    sl     = sig.get("sl") or None
    conf   = sig.get("confidence") or 0.0

    # Build vote prompt context
    rsi         = indic["rsi"]
    rsi_desc    = "quá mua" if rsi > 70 else ("quá bán" if rsi < 30 else "trung tính")
    vs_ma20_pct = (close / indic["ma20"] - 1) * 100 if indic["ma20"] else 0
    vs_ma20_desc = "trên" if vs_ma20_pct >= 0 else "dưới"
    action_upper = {"buy": "MUA 🟢", "sell": "BÁN 🔴"}.get(action, "KHÔNG GIAO DỊCH 🟡")

    def _fmt_price(v: Optional[float], ref: float) -> str:
        if not v or v <= 0:
            return "—"
        return f"{v:,.0f} VND ({(v/ref-1)*100:+.1f}%)"

    vote_prompt = _TICKER_VOTE_PROMPT.format(
        ticker=ticker,
        close=close,
        rsi=rsi, rsi_desc=rsi_desc,
        ma20=indic["ma20"], vs_ma20_desc=vs_ma20_desc, vs_ma20_pct=vs_ma20_pct,
        vol_ratio=indic["vol_ratio"], trend_5d=indic["trend_5d"],
        action_upper=action_upper,
        entry_str=f"{entry:,.0f} VND" if entry else "—",
        tp_str=_fmt_price(tp, entry),
        sl_str=_fmt_price(sl, entry),
    )

    # Step 2: collect independent votes (short, fast — 150 tokens each)
    available = [a for a in agents if getattr(a, "is_available", False)]
    votes: list[dict] = []
    for ag in available:
        text, err = ag.generate(vote_prompt, max_tokens=150)
        if err or not text:
            continue
        # Parse structured response
        vote_action, agrees, reason = "hold", None, ""
        for line in text.splitlines():
            l = line.strip()
            if l.upper().startswith("ĐÁNH GIÁ:"):
                val = l.split(":", 1)[1].strip().lower()
                if "mua" in val:
                    vote_action = "buy"
                elif "bán" in val or "ban" in val:
                    vote_action = "sell"
                else:
                    vote_action = "hold"
            elif "ĐỒNG Ý" in l.upper() or "DONG Y" in l.upper():
                agrees = ("CÓ" in l.upper() or " CO" in l.upper()
                          or "YES" in l.upper() or "ĐỒNG Ý: CÓ" in l.upper())
            elif l.upper().startswith("LÝ DO:") or l.upper().startswith("LY DO:"):
                reason = l.split(":", 1)[1].strip()
        votes.append({
            "agent":   ag.name,
            "action":  vote_action,
            "agrees":  agrees,
            "reason":  reason,
            "raw":     text,
        })

    # Step 3: compute consensus
    if not votes:
        consensus_action   = action
        agreement_rate     = 0.0
        strategy_agree_rate = 0.0
    else:
        counts             = Counter(v["action"] for v in votes)
        consensus_action   = counts.most_common(1)[0][0]
        agreement_rate     = counts[consensus_action] / len(votes)
        n_agree_strategy   = sum(1 for v in votes if v.get("agrees") is True)
        strategy_agree_rate = n_agree_strategy / len(votes)

    # Step 4: lead agent writes full explanation — reuse already-computed signal/indicators
    explanation = ""
    lead = available[0] if available else None
    if lead:
        from datetime import date as _date_cls

        def _price_str(v: Optional[float], ref: float) -> tuple[str, str]:
            if not v or v <= 0:
                return "—", ""
            pct = (v / ref - 1) * 100
            return f"{v:,.0f} VND", f"{pct:+.1f}%"

        tp_str, tp_pct = _price_str(tp, entry)
        sl_str, sl_pct = _price_str(sl, entry)
        rr = "—"
        if tp and sl and entry and abs(entry - sl) > 0:
            rr = f"{abs((tp - entry) / (entry - sl)):.1f}"

        # Fetch news context for the ticker (same as analyze_ticker)
        _news_section_c = ""
        try:
            from vnstock_news import news_for_ticker as _nft_c
            _ticker_news_c = _nft_c(ticker)
            if _ticker_news_c:
                _lines_c = ["\n=== TIN TỨC GẦN ĐÂY ==="]
                for _n in _ticker_news_c[:5]:
                    _title_c   = (_n.get("news_title") or "").strip()
                    _summary_c = (_n.get("news_short_content") or _n.get("news_sub_title") or "").strip()
                    _date_c    = _n.get("_date_sort", "")[:10]
                    if _title_c:
                        _lines_c.append(f"• [{_date_c}] {_title_c}")
                        if _summary_c:
                            _lines_c.append(f"  {_summary_c[:200]}")
                _news_section_c = "\n".join(_lines_c) + "\n"
        except Exception:
            pass

        analysis_prompt = _TICKER_ANALYSIS_PROMPT.format(
            ticker=ticker,
            date=_date_cls.today().isoformat(),
            close=close,
            rsi=rsi, rsi_desc=rsi_desc,
            ma20=indic["ma20"], vs_ma20_desc=vs_ma20_desc, vs_ma20_pct=vs_ma20_pct,
            vol_ratio=indic["vol_ratio"], trend_5d=indic["trend_5d"],
            high_52w=indic["high_52w"], low_52w=indic["low_52w"],
            strategy_name=active["name"],
            action_upper=action_upper, confidence=conf,
            entry_str=f"{entry:,.0f} VND" if entry else "—",
            tp_str=tp_str, tp_pct=tp_pct,
            sl_str=sl_str, sl_pct=sl_pct, rr=rr,
            news_block=_news_section_c,
        )
        text, err = lead.generate(analysis_prompt, max_tokens=500)
        explanation = text or (f"Lỗi AI: {err}" if err else "")

    return {
        "action":               action,            # strategy signal (deterministic)
        "consensus_action":     consensus_action,  # majority vote across agents
        "agreement_rate":       agreement_rate,    # % agents that share consensus_action
        "strategy_agree_rate":  strategy_agree_rate,  # % agents that agree with strategy signal
        "entry":  entry,
        "tp":     tp,
        "sl":     sl,
        "confidence": conf,
        "votes":  votes,
        "explanation":   explanation,
        "strategy_name": active["name"],
        "strategy_id":   active["id"],
        "indicators":    indic,
        "n_agents":      len(votes),
    }
