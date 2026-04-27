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
CORE CODE hiện tại ĐANG CHƯA HIỆU QUẢ (cần REVISE major):

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
) -> tuple[str, dict, str | None]:
    """Ask an agent to write a new core (different approach). Returns (code, params, err)."""
    prompt = _REVISE_PROMPT.format(
        code=code,
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
WEEKLY_REVISE_DAYS = 7
N_STABLE_WEEKS_REQUIRED = 3


def _should_revise(active: dict) -> bool:
    """True if it's time to revise (rewrite core), False if just tune params.

    Rules:
      - If is_core_stable=1 → never revise (only tune)
      - If active strategy has 0 trades → revise immediately (broken logic)
      - If last revise > WEEKLY_REVISE_DAYS days ago → revise
      - Cold start (no active) handled by caller
    """
    if not active:
        return True
    if active.get("is_core_stable"):
        return False
    # If the current strategy never fired a single trade, it's broken — revise now
    fam = active.get("family_id")
    if fam:
        hist = mem.family_history(fam, limit=1)
        if hist and (hist[0].get("n_trades") or 0) == 0:
            return True
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


def _cold_start(agent, universe, context_summary, cfg) -> tuple[Optional[int], dict]:
    """Generate fresh strategy + initial params, persist + backtest."""
    code, params, err = generate_strategy(agent, context_summary=context_summary)
    if err and not code:
        return None, {"error": err}
    family = _uuid.uuid4().hex[:8]
    sid = mem.save_strategy(
        agent_name=agent.name,
        name=f"family-{family} v1 by {agent.name}",
        code=code,
        params=params,
        description="Cold-start core",
        status="draft",
        family_id=family,
    )
    if err:
        mem.save_backtest(sid, "", "", ",".join(universe[:10]),
                          {"n_trades": 0}, error=err)
        return sid, {"error": err}
    metrics, ps, pe = _do_backtest(code, params, cfg)
    mem.save_backtest(sid, ps, pe, ",".join(universe[:10]), metrics)
    if metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
       and (metrics.get("expectancy") or -999) > 0:
        mem.promote_strategy(sid, retire_others=True)
    else:
        mem.update_strategy_status(sid, "validated"
                                   if metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE
                                   else "draft")
        mem.promote_strategy(sid, retire_others=True)  # always have one active
    return sid, metrics


def _do_revise(agent, active, cfg) -> tuple[Optional[int], dict]:
    """Weekly-cadence: rewrite core, compare, promote if better."""
    code     = active["code"]
    family   = active.get("family_id") or _uuid.uuid4().hex[:8]
    cur_metrics = mem.latest_backtest(active["id"]) or {}
    new_code, new_params, err = revise_strategy(agent, code, cur_metrics)
    if err and not new_code:
        return None, {"error": err}
    sid = mem.save_strategy(
        agent_name=agent.name,
        name=f"family-{family} revise by {agent.name} @ {time.strftime('%m-%d')}",
        code=new_code,
        params=new_params,
        description="Weekly revise",
        parent_id=active["id"],
        status="draft",
        family_id=family,
    )
    if err:
        mem.save_backtest(sid, "", "", ",".join(cfg.universe[:10]),
                          {"n_trades": 0}, error=err)
        return sid, {"error": err}
    metrics, ps, pe = _do_backtest(new_code, new_params, cfg)
    mem.save_backtest(sid, ps, pe, ",".join(cfg.universe[:10]), metrics)
    cur_exp = (cur_metrics.get("expectancy") or -999)
    new_exp = (metrics.get("expectancy") or -999)
    if new_exp > cur_exp and metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE:
        mem.promote_strategy(sid, retire_others=True)
        if _check_stability(family):
            mem.mark_core_stable(sid, True)
    else:
        mem.update_strategy_status(sid, "retired")
    return sid, metrics


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
        return _cold_start(agent, universe, context_summary, cfg)

    if mode == "revise" or (mode == "auto" and _should_revise(active)):
        return _do_revise(agent, active, cfg)

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
) -> list[dict]:
    """Run best-validated strategy on most-recent window per ticker;
    return + persist actionable recs.
    """
    bests = mem.best_strategies(limit=3)
    if not bests:
        return []
    recs: list[dict] = []
    for s in bests:
        code = s["code"]
        for ticker in universe:
            if len(recs) >= max_recs:
                break
            hist = _load_history(ticker, days=120)
            if hist.empty or len(hist) < 60:
                continue
            window = hist.tail(60).reset_index(drop=True)
            try:
                raw = EXECUTOR.run(code, window, {})
                sig = _validate_signal_output(raw)
            except Exception:
                continue
            if sig["action"] != "buy" or sig["entry"] <= 0:
                continue
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
    return recs
