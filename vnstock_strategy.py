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
    """Option A: AST whitelist + restricted exec + multiprocessing timeout."""

    def __init__(self, timeout_s: float = STRATEGY_TIMEOUT_S):
        self.timeout_s = timeout_s

    def run(self, code: str, df: pd.DataFrame, params: dict) -> dict:
        # Pre-flight AST validation in current process — cheap, fail-fast
        _validate_ast(code)

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
EXECUTOR: StrategyExecutor = InProcessExecutor()


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
chứng khoán Việt Nam dưới dạng PYTHON CODE PURE (không markdown, không giải thích).

Yêu cầu nghiêm ngặt:
- Định nghĩa hàm: def signal(df, params) -> dict
- df là pandas DataFrame có cột: time, open, high, low, close, volume (index 0..N-1, mới nhất ở cuối)
- Trả về dict: {{"action": "buy"|"sell"|"hold", "entry": float, "tp": float, "sl": float, "confidence": 0..1}}
- KHÔNG được dùng: import, open, exec, eval, file IO, network, subprocess, os, sys, requests
- Chỉ dùng: pd, np, math (đã có sẵn trong scope)
- entry/tp/sl phải là giá tuyệt đối (VND), không phải %
- Logic phải chạy được với window 60 ngày, không phụ thuộc data ngoài df

Bối cảnh hiện tại để hint chiến lược:
{context}

{prior_feedback}

Output: chỉ Python code, KHÔNG có ```python``` wrapper, không text khác.
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


def generate_strategy(
    agent,
    context_summary: str = "",
    prior_feedback: str = "",
) -> tuple[str, str | None]:
    """Ask an agent to generate a fresh strategy. Returns (code, error)."""
    prompt = _STRATEGY_PROMPT.format(
        context=context_summary or "Thị trường VN, large-cap, daily timeframe.",
        prior_feedback=prior_feedback or "(không có feedback ưu tiên)",
    )
    text, err = agent.generate(prompt, max_tokens=1500)
    if err:
        return "", err
    code = _strip_code_fences(text)
    try:
        _validate_ast(code)
    except StrategyValidationError as e:
        return code, f"AST rejected: {e}"
    if "def signal" not in code:
        return code, "Missing `def signal()` definition"
    return code, None


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
def develop_and_backtest(
    agent,
    universe: list[str],
    context_summary: str = "",
    n_iterations: int = 2,
) -> tuple[Optional[int], dict]:
    """Generate → backtest → improve → backtest. Persist all to memory.

    Returns (final_strategy_id, last_metrics).
    """
    code, err = generate_strategy(agent, context_summary=context_summary)
    if err and not code:
        return None, {"error": err}
    sid = mem.save_strategy(
        agent_name=agent.name,
        name=f"{agent.name} draft @ {time.strftime('%Y-%m-%d %H:%M')}",
        code=code,
        description="Auto-generated by train loop",
        status="draft",
    )
    cfg = BacktestConfig(universe=universe)
    if err:
        # Validation failed — record but skip backtest
        mem.save_backtest(sid, "", "", ",".join(universe[:10]),
                          {"n_trades": 0}, error=err)
        return sid, {"error": err}

    metrics = backtest(code, cfg)
    period_start = (pd.Timestamp.now() - pd.Timedelta(days=cfg.lookback_days)).date().isoformat()
    period_end   = pd.Timestamp.now().date().isoformat()
    mem.save_backtest(sid, period_start, period_end,
                      ",".join(universe[:10]), metrics)

    cur_code = code
    cur_metrics = metrics
    cur_sid = sid

    for _ in range(max(0, n_iterations)):
        if cur_metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
           and cur_metrics.get("expectancy", -999) > 0:
            mem.update_strategy_status(cur_sid, "validated")
            break
        new_code, err = improve_strategy(agent, cur_code, cur_metrics)
        if err and not new_code:
            break
        new_sid = mem.save_strategy(
            agent_name=agent.name,
            name=f"{agent.name} v{_ + 2} @ {time.strftime('%Y-%m-%d %H:%M')}",
            code=new_code,
            description="Improvement iteration",
            parent_id=cur_sid,
            status="draft",
        )
        if err:
            mem.save_backtest(new_sid, "", "", ",".join(universe[:10]),
                              {"n_trades": 0}, error=err)
            cur_sid = new_sid
            continue
        new_metrics = backtest(new_code, cfg)
        mem.save_backtest(new_sid, period_start, period_end,
                          ",".join(universe[:10]), new_metrics)
        # Only switch if strictly better expectancy
        if (new_metrics.get("expectancy") or -999) > (cur_metrics.get("expectancy") or -999):
            cur_code, cur_metrics, cur_sid = new_code, new_metrics, new_sid

    if cur_metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
       and cur_metrics.get("expectancy", -999) > 0:
        mem.update_strategy_status(cur_sid, "validated")
    return cur_sid, cur_metrics


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
