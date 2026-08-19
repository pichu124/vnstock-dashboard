"""
vnstock_strategy.py — Sandboxed strategy executor + backtest engine.

Architecture
------------
  StrategyExecutor (ABC)   — sandbox interface; run(code, df, params) -> dict
  InProcessExecutor        — AST whitelist + restricted exec + mp timeout (Option A)
  SubprocessExecutor       — placeholder for Option B (subprocess + cwd isolation)

  Backtest                 — apply signal() over historical OHLCV per ticker
  generate_strategy()      — ask an agent to draft a strategy

Strategy contract
-----------------
  Generated code MUST define a single function:

      def signal(df: pd.DataFrame, params: dict) -> dict:
          # df has columns: time, open, high, low, close, volume (last N rows)
          # return: {"action": "buy"|"sell"|"hold",
          #          "entry": float, "tp": float, "sl": float,
          #          "confidence": 0..1}

Sandbox layers (siết lại 06/08/2026 sau audit — xem docs/CLAUDE-NOTES.md)
------------------------------------------------------------------------
  1. AST gate — chặn Import, tên cấm, tên MODULE cấm, attribute dunder,
     attribute nguy hiểm (to_csv/query/eval/mro/format…), và mặc định mọi
     attribute NGOÀI danh sách trắng `_ALLOWED_ATTRS`.
  2. Restricted globals — pd/np/math KHÔNG còn là module thật mà là "khay"
     chỉ chứa hàm đã duyệt (`_make_safe_namespace`). Đây là lớp bịt lỗ hổng
     gốc: `pd.io.common.os.system(...)` từng lọt vì toàn tên thường.
  3. multiprocessing timeout — kill if exceeds STRATEGY_TIMEOUT_S
  4. Output schema validation — reject if missing keys or wrong types

CẢNH BÁO: đây là sandbox "best effort" cho code do LLM sinh trên máy CÁ NHÂN,
KHÔNG phải hàng rào chống attacker có chủ đích. Muốn chắc thì chạy subprocess
hạ quyền/seccomp. Thêm điểm dùng model/API mới vào sandbox → thêm test tấn
công vào tests/test_strategy_sandbox.py.
"""
from __future__ import annotations

import ast
import json
import math
import multiprocessing as mp
import os
import sys
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

# ── Tầng thời gian (13/08 — user chốt "theo dõi cả ngắn/dài") ───────────────
# Số chọn từ ĐO THỰC trên máy user (vnstock_reachability, 30 mã VN30 × 500
# phiên, _meta/reachability.json):
#   horizon   p60 MFE (×ATR)   TP 2.5×ATR với tới
#      5d          1.30              16%   ← TP 2.5–4×ATR hiện tại gần như ảo
#     20d          2.89              46%   ← khớp đúng dải tp_atr_mult 2.5–3.0
#     40d          4.30              61%   (vốn nằm gấp đôi, MAE p50 −7.5%)
# → tier "position" lấy 20 phiên: TP hiện hành trở nên VỚI TỚI ĐƯỢC mà vốn
# không bị giam quá lâu. 40d để sau nếu user muốn thêm tầng nữa.
#
# BẤT BIẾN step ≥ horizon: hai lệnh backtest chồng cửa sổ là CÙNG một cú sóng
# đếm nhiều lần — mẫu "độc lập" giả làm p-value đẹp giả, kiểm định chống-ăn-may
# thành trang trí. Có test canh (tests/test_strategy_tiers.py).
TIER_CONFIGS: "dict[str, dict]" = {
    "short":    {"horizon_days": 5,  "step_days": 5,  "lookback_days": 365},
    "position": {"horizon_days": 20, "step_days": 20, "lookback_days": 730},
}


# `horizon_days` LÀ SỐ PHIÊN, không phải ngày lịch — backtest cắt cửa sổ theo
# BAR (`hist.head(horizon)`). Chỗ nào chỉ có ngày lịch trong tay (nhãn hiển thị,
# bộ lọc brief) thì quy đổi qua đây thay vì so thẳng: 5 phiên ≈ 7 ngày lịch,
# 20 phiên ≈ 28 ngày. So thẳng là đóng/ẩn lệnh SỚM ~30% (vết 19/08).
# Xấp xỉ 7/5 CỐ Ý bỏ qua lễ tết: nó chỉ dùng cho nhãn và bộ lọc, còn quyết định
# ĐÓNG LỆNH thì đếm bar thật (`reconcile_recommendations`).
_CALENDAR_PER_SESSION = 7 / 5


def calendar_days_for_sessions(sessions: int) -> int:
    """Số ngày lịch tối thiểu để trôi qua `sessions` phiên (làm tròn LÊN)."""
    import math as _math
    try:
        n = int(sessions)
    except Exception:
        return 0
    return max(n, _math.ceil(n * _CALENDAR_PER_SESSION))


def tier_config(tier: str, universe: "list[str]") -> "BacktestConfig":
    """BacktestConfig chuẩn cho một tier. Tier lạ → ValueError (không đoán)."""
    if tier not in TIER_CONFIGS:
        raise ValueError(f"tier không khai báo: {tier!r} (có: {sorted(TIER_CONFIGS)})")
    t = TIER_CONFIGS[tier]
    return BacktestConfig(universe=universe, lookback_days=t["lookback_days"],
                          horizon_days=t["horizon_days"], step_days=t["step_days"])
# 10 → 30 (user chốt 13/08): #32 đạt p=0.040 với vỏn vẹn 19 lệnh sau khi tune
# co mẫu từ 67 — thống kê trên mẫu mỏng + chọn lọc trong-mẫu là công thức
# overfit. 30 lệnh là mức tối thiểu để một verdict "đạt" mang được tiền thật;
# hạ xuống là quyết định khẩu vị rủi ro của user, không phải tinh chỉnh kỹ thuật.
MIN_TRADES_TO_VALIDATE = 30

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

# ── Attribute NGUY HIỂM — chặn cứng, không tắt được (audit 06/08) ──────────
# Cổng kiểm cũ chặn `open` nhưng KHÔNG đụng `df.to_csv(...)` — ghi file y hệt
# mà chỉ là attribute thường. Tương tự df.query/df.eval thực thi CHUỖI, và
# type(x).mro() leo ngược cây lớp tới `object` bằng method thường (bộ lọc
# dunder không thấy). `.format` đọc được dunder qua string literal — chỗ AST
# không soi vào được ("{0.__class__}".format(df)).
_FORBIDDEN_ATTRS = {
    # ghi file qua chính đối tượng dữ liệu
    "to_csv", "to_pickle", "to_parquet", "to_json", "to_excel", "to_sql",
    "to_hdf", "to_feather", "to_stata", "to_clipboard", "to_gbq", "to_orc",
    "to_xml", "to_latex", "to_string_io", "savefig", "savez", "tofile",
    "save", "write", "writelines", "dump", "dumps",
    # thực thi chuỗi
    "query", "eval", "exec", "compile", "pipe_eval",
    # leo cây lớp / phản chiếu không cần dunder
    "mro", "mro_entries", "subclasses", "func_globals", "gi_frame",
    "cr_frame", "f_globals", "f_locals", "f_builtins",
    # giao thức format đọc dunder qua chuỗi
    "format", "format_map",
    # gọi hệ điều hành nếu bằng cách nào đó chạm được module
    "system", "popen", "spawn", "spawnv", "fork", "execv", "execve",
    "startfile", "call", "check_output", "run_shell",
    # đọc/ghi qua accessor lạ
    "plot", "style", "attrs",
}

# ── Attribute ĐƯỢC PHÉP — danh sách TRẮNG (audit 06/08) ────────────────────
# Điểm mấu chốt của đợt sửa: danh sách ĐEN sót một tên là thành LỖ HỔNG,
# danh sách TRẮNG sót một tên chỉ là BẤT TIỆN (thêm vào đây rồi chạy lại).
# Gom từ chiến lược mẫu trong _STRATEGY_PROMPT + các idiom quant thông dụng.
# Kill-switch: VNSTOCK_STRATEGY_STRICT_ATTRS=0 → lùi về chế độ chỉ chặn
# _FORBIDDEN_ATTRS + dunder (proxy module VẪN bật, không tắt được).
_ALLOWED_ATTRS = {
    # truy cập/định vị
    "iloc", "loc", "at", "iat", "values", "index", "columns", "name",
    "shape", "size", "dtype", "dtypes", "empty", "T", "str", "dt", "array",
    "flat", "ndim", "nbytes", "real", "imag",
    # thống kê / tổng hợp
    "mean", "median", "sum", "std", "var", "min", "max", "count", "prod",
    "quantile", "mode", "sem", "skew", "kurt", "corr", "cov", "nunique",
    "value_counts", "describe", "cumsum", "cumprod", "cummax", "cummin",
    "rank", "pct_change", "diff", "abs", "round", "clip", "product",
    "nanmean", "nanstd", "nanmedian", "nansum", "nanmax", "nanmin",
    "argmax", "argmin", "idxmax", "idxmin", "nlargest", "nsmallest",
    # cửa sổ trượt
    "rolling", "ewm", "expanding", "shift", "resample", "apply", "agg",
    "aggregate", "transform", "pipe", "map", "applymap",
    # chọn / biến đổi
    "head", "tail", "drop", "dropna", "fillna", "ffill", "bfill", "replace",
    "reset_index", "set_index", "sort_values", "sort_index", "reindex",
    "rename", "astype", "copy", "squeeze", "to_list", "tolist", "to_numpy",
    "item", "unique", "isin", "between", "where", "mask", "groupby",
    "iterrows", "itertuples", "items", "keys", "get", "reshape", "ravel",
    "flatten", "take", "repeat", "stack", "unstack", "melt", "pivot",
    "combine", "combine_first", "align", "join", "assign", "insert",
    "interpolate", "shift_periods", "first", "last", "sample", "duplicated",
    "drop_duplicates", "nan_to_num", "asfreq",
    # toán tử dạng method
    "add", "sub", "mul", "div", "truediv", "floordiv", "mod", "pow",
    "radd", "rsub", "rmul", "rdiv", "gt", "lt", "ge", "le", "eq", "ne",
    "any", "all", "notna", "isna", "isnull", "notnull", "isfinite",
    "logical_and", "logical_or", "logical_not", "invert", "sign", "sqrt",
    "log", "log1p", "log10", "log2", "exp", "expm1", "floor", "ceil",
    "trunc", "maximum", "minimum", "dot", "sort", "reverse", "append",
    "extend", "update", "setdefault", "pop", "clear", "difference",
    "intersection", "union", "issubset", "add_prefix", "add_suffix",
    # accessor .dt / .str (chiến lược lọc theo phiên/ngày)
    "year", "month", "day", "hour", "minute", "second", "date", "time",
    "weekday", "dayofweek", "dayofyear", "quarter", "days", "seconds",
    "total_seconds", "normalize", "floor_ts", "strftime",
    "contains", "startswith", "endswith", "lower", "upper", "strip",
    "lstrip", "rstrip", "split", "rsplit", "len", "cat", "zfill",
    # số học python thuần
    "bit_length", "is_integer", "conjugate", "numerator", "denominator",
    "hypot", "fabs", "fmod", "copysign", "degrees", "radians", "atan",
    "atan2", "asin", "acos", "sin", "cos", "tan", "tanh", "sinh", "cosh",
    "isnan", "isinf", "gcd", "factorial", "comb", "perm", "erf", "gamma",
    "pi", "e", "tau", "inf", "nan", "nanargmax", "nanargmin",
    # dựng đối tượng pandas/numpy (dùng qua khay pd./np.)
    "DataFrame", "Series", "Index", "concat", "merge", "to_numeric",
    "to_datetime", "to_timedelta", "date_range", "bdate_range", "Timestamp",
    "Timedelta", "NaT", "NA", "cut", "qcut", "factorize", "get_dummies",
    "array_split", "asarray", "arange", "linspace", "zeros", "ones", "full",
    "percentile", "corrcoef", "polyfit", "polyval", "concatenate", "vstack",
    "hstack", "column_stack", "diag", "identity", "eye", "cumproduct",
    "float64", "float32", "int64", "int32", "bool_", "errstate",
    # ── Bổ sung VÒNG 2 (red-team 06/08: 6/12 chiến lược thật CHẾT oan) ────
    # Tên cột OHLCV truy cập kiểu attribute — `df.close` là idiom cực phổ
    # biến, thiếu nó là giết phần lớn chiến lược ngay dòng đầu.
    "close", "high", "low", "open", "volume", "time", "price", "value",
    # alias đầy-đủ-tên của toán tử (pandas có cả 2 dạng)
    "subtract", "multiply", "divide", "kurtosis", "to_frame",
    # numpy: xếp hạng / thống kê / lượng giác còn thiếu
    "argsort", "average", "gradient", "ptp", "arctan", "arctan2", "arcsin",
    "arccos", "count_nonzero", "convolve", "isclose", "allclose", "roll",
    "nanpercentile", "nanquantile", "searchsorted", "power", "greater",
    "less", "equal", "greater_equal", "less_equal", "not_equal", "mod",
    "divmod", "true_divide", "floor_divide", "square", "cbrt", "reciprocal",
    # pandas: dọn dữ liệu / chọn cột / tra cứu
    "last_valid_index", "first_valid_index", "equals", "select_dtypes",
    "filter", "corrwith", "cumcount", "get_loc", "tz_localize", "tz_convert",
    "ohlc", "at_time", "between_time", "swaplevel", "droplevel", "explode",
    "nunique_approx", "clip_lower", "clip_upper", "truncate", "asof",
}


# ── String-dispatch của pandas (red-team 06/08 phá được vòng vá 1) ─────────
# `.apply`/`.agg`/`.aggregate`/`.transform` nhận TÊN METHOD DẠNG CHUỖI rồi tự
# `getattr(obj, name)(...)` lúc chạy. Tên nằm trong string literal (ast.Constant)
# nên MỌI kiểm tra trên ast.Attribute — kể cả `_FORBIDDEN_ATTRS` vốn đã có
# 'to_csv' — đều không nhìn thấy. Red-team đã ghi được file tuỳ ý (path +
# nội dung do attacker chọn), kể cả .pth vào site-packages = code chạy mỗi
# lần khởi động Python. Lưu ý: `df` là DataFrame THẬT truyền vào signal(),
# KHÔNG qua khay — nên lớp 2 không đỡ được đường này.
#
# Luật: đối số đầu PHẢI là `lambda` viết thẳng trong code (đã được AST soi).
# Cố ý KHÔNG đi theo hướng "cấm chuỗi trông giống tên nguy hiểm": chuỗi ghép
# động ('to_' + 'csv') hay biến chuỗi sẽ lách được ngay. `map`/`pipe` chưa
# string-dispatch ở pandas 3.0.3 nhưng áp cùng luật cho chắc về sau.
_DISPATCH_ATTRS = {
    "apply", "applymap", "agg", "aggregate", "transform", "map", "pipe",
}


def _check_dispatch_call(node: "ast.Call") -> None:
    """Chặn string-dispatch trên nhóm `_DISPATCH_ATTRS`."""
    if not node.args or not isinstance(node.args[0], ast.Lambda):
        raise StrategyValidationError(
            f"`.{node.func.attr}(...)` chỉ nhận `lambda` viết thẳng làm đối số "
            f"đầu. Dạng chuỗi (vd .agg('to_csv', ...)) bị cấm vì pandas sẽ tự "
            f"gọi method theo tên — đường thoát sandbox đã xác nhận 06/08."
        )
    for kw in node.keywords:
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            raise StrategyValidationError(
                f"`.{node.func.attr}(...)`: đối số chuỗi `{kw.arg}=` bị cấm "
                f"(đường string-dispatch)."
            )


def _strict_attrs_enabled() -> bool:
    """Danh sách trắng attribute bật mặc định; kill-switch theo nếp repo cho
    trường hợp chiến lược ĐANG CHẠY dùng API hợp lệ mà danh sách còn thiếu
    (báo lại để bổ sung — đừng để tắt lâu dài)."""
    return (os.environ.get("VNSTOCK_STRATEGY_STRICT_ATTRS") or "1") \
        .strip().lower() not in ("0", "false", "off")


class StrategyValidationError(ValueError):
    """Raised when strategy code fails AST whitelist or output contract."""


class StrategySandboxError(RuntimeError):
    """Sandbox chặn ở tầng RUNTIME (lớp 2) — vd chạm tới thứ không nằm trong
    khay pd/np/math. Khác StrategyValidationError (chặn ở tầng AST)."""


def _validate_ast(code: str) -> None:
    """Parse code and reject if any blacklisted construct appears.

    Lớp 1 của sandbox. Sau audit 06/08 kiểm 5 thứ: import, tên cấm, tên
    MODULE cấm (trước đây `_FORBIDDEN_MODULES` là code chết), attribute dunder,
    attribute nguy hiểm, và — mặc định — attribute NGOÀI danh sách trắng.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise StrategyValidationError(f"SyntaxError: {e}") from e

    strict_attrs = _strict_attrs_enabled()

    # ── Lượt A: chốt các chỗ gọi dispatch HỢP LỆ ──────────────────────────
    # Red-team vòng 2 phá được luật "kiểm tại chỗ gọi" vì bound method trong
    # Python là OBJECT HẠNG NHẤT: `w = df.agg` rồi `w('to_csv', 0, path)` làm
    # node.func thành ast.Name → luật không bao giờ chạy. Biến thể ẩn danh
    # `[df.agg][0](...)` và `(lambda f: f(...))(df.agg)` cũng vậy.
    # Nên luật phải theo THAM CHIẾU, không theo chỗ gọi: tên dispatch CHỈ
    # được xuất hiện đúng ở vị trí callee của một lời gọi đã qua kiểm; mọi
    # cách nhắc tới nó như một giá trị đều bị từ chối.
    ok_dispatch_refs = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _DISPATCH_ATTRS):
            _check_dispatch_call(node)
            ok_dispatch_refs.add(id(node.func))

    for node in ast.walk(tree):
        # No imports at all
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise StrategyValidationError("Import statements are not allowed")

        # No forbidden name access. `_FORBIDDEN_MODULES` nay ĐƯỢC DÙNG THẬT —
        # trước 06/08 nó chỉ nằm đó cho đẹp (audit: dead code).
        if isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                raise StrategyValidationError(f"Forbidden name: {node.id}")
            if node.id in _FORBIDDEN_MODULES:
                raise StrategyValidationError(f"Forbidden module name: {node.id}")

        if isinstance(node, ast.Attribute):
            attr = node.attr
            # No dunder attribute access (except __init__/__name__)
            if attr.startswith("__") and attr.endswith("__"):
                if attr not in _ALLOWED_DUNDERS:
                    raise StrategyValidationError(
                        f"Forbidden dunder attribute: {attr}"
                    )
            if attr in _FORBIDDEN_ATTRS:
                raise StrategyValidationError(f"Forbidden attribute: .{attr}")
            if attr in _DISPATCH_ATTRS and id(node) not in ok_dispatch_refs:
                # Tham chiếu tới method dispatch mà KHÔNG phải lời gọi trực
                # tiếp (gán ra biến, nhét vào list, truyền làm đối số…) —
                # đường thoát vòng 2 (red-team 06/08).
                raise StrategyValidationError(
                    f"`.{attr}` chỉ được GỌI TRỰC TIẾP với `lambda` "
                    f"(vd `.{attr}(lambda x: …)`); không được gán ra biến "
                    f"hay truyền đi như một giá trị — bound method là object "
                    f"hạng nhất nên đó là đường lách string-dispatch."
                )
            if strict_attrs and attr not in _ALLOWED_ATTRS:
                raise StrategyValidationError(
                    f"Attribute `.{attr}` không nằm trong danh sách cho phép "
                    f"của sandbox. API hợp lệ thì thêm vào _ALLOWED_ATTRS "
                    f"(vnstock_strategy.py); tắt tạm: "
                    f"VNSTOCK_STRATEGY_STRICT_ATTRS=0"
                )

        # No file/IO function calls by name
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_NAMES:
                raise StrategyValidationError(
                    f"Forbidden function call: {node.func.id}"
                )
            # String-dispatch (red-team 06/08) — xem `_check_dispatch_call`
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in _DISPATCH_ATTRS):
                _check_dispatch_call(node)


def _safe_builtins() -> dict:
    # VÒNG 2 (red-team 06/08): thiếu `pow` và MỌI lớp exception → chiến lược
    # bọc try/except (nếp quant chuẩn để không vỡ vì NaN/chia 0) chết ngay ở
    # runtime với NameError. Lớp exception không mở đường thoát nào: đi tiếp
    # từ chúng đều cần dunder, vốn đã bị AST chặn.
    safe_names = (
        "abs all any bool dict divmod enumerate filter float int isinstance "
        "issubclass len list map max min pow print range reversed round set "
        "slice sorted str sum tuple type zip True False None "
        "Exception ArithmeticError ValueError TypeError KeyError IndexError "
        "ZeroDivisionError OverflowError FloatingPointError RuntimeError "
        "AttributeError StopIteration"
    ).split()
    real_builtins = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
    out = {n: real_builtins[n] for n in safe_names if n in real_builtins}
    out["__name__"] = "strategy_sandbox"
    return out


# ── Lớp 2: "khay" thay cho module thật ────────────────────────────────────
# Gốc rễ lỗ hổng audit 06/08: sandbox đưa NGUYÊN module pandas vào scope, mà
# pandas có `import os` bên trong nên `pd.io.common.os.system(...)` chạm tới
# shell — toàn tên thường nên cổng kiểm AST không thấy gì sai. Nay chiến lược
# chỉ nhận một cái khay chứa đúng các hàm đã duyệt: `pd.io` KHÔNG TỒN TẠI.
# Lớp này KHÔNG có kill-switch (khác danh sách trắng attribute).

def _make_safe_namespace(label: str, module, allowed: set):
    """Khay chỉ-đọc chứa đúng `allowed` của `module`.

    Members giữ trong CLOSURE và instance có `__slots__ = ()` — instance
    không mang thuộc tính nào, nên MỌI truy cập đều rơi vào `__getattr__` và
    bị kiểm. Không có đường vòng nào lấy lại được module gốc.
    """
    members = {a: getattr(module, a) for a in allowed if hasattr(module, a)}

    class _SafeNamespace:
        __slots__ = ()

        def __getattr__(self, item):
            try:
                return members[item]
            except KeyError:
                raise StrategySandboxError(
                    f"sandbox: `{label}.{item}` không nằm trong danh sách "
                    f"cho phép ({len(members)} hàm)"
                ) from None

        def __setattr__(self, item, value):
            raise StrategySandboxError(
                f"sandbox: không được gán `{label}.{item}`")

        def __repr__(self):
            return f"<sandbox {label}: {len(members)} hàm được phép>"

    return _SafeNamespace()


# Hàm/hằng module-level chiến lược được dùng. Cố ý KHÔNG có read_csv/read_*,
# không submodule (pd.io/np.f2py…), không set_option.
_PD_SAFE = {
    "DataFrame", "Series", "Index", "concat", "merge", "isna", "notna",
    "isnull", "notnull", "to_numeric", "to_datetime", "to_timedelta",
    "date_range", "bdate_range", "Timestamp", "Timedelta", "NaT", "NA",
    "cut", "qcut", "factorize", "get_dummies", "unique",
}
_NP_SAFE = {
    "nan", "inf", "pi", "e", "array", "asarray", "arange", "linspace",
    "zeros", "ones", "full", "where", "clip", "abs", "sqrt", "log", "log1p",
    "log10", "log2", "exp", "expm1", "power", "sign", "maximum", "minimum",
    "mean", "median", "std", "var", "sum", "prod", "cumsum", "cumprod",
    "diff", "corrcoef", "cov", "percentile", "quantile", "nanmean",
    "nanstd", "nanmedian", "nansum", "nanmax", "nanmin", "nanargmax",
    "nanargmin", "isnan", "isinf", "isfinite", "argmax", "argmin", "max",
    "min", "round", "floor", "ceil", "trunc", "dot", "polyfit", "polyval",
    "sort", "concatenate", "vstack", "hstack", "column_stack", "all", "any",
    "logical_and", "logical_or", "logical_not", "greater", "less", "equal",
    "tanh", "sinh", "cosh", "sin", "cos", "tan", "float64", "float32",
    "int64", "int32", "bool_", "errstate", "nan_to_num", "sign",
    # VÒNG 2 — red-team: 4 tên dưới TỪNG có trong danh sách trắng AST nhưng
    # THIẾU ở khay → qua cổng rồi chết ở runtime (bất nhất 2 tầng).
    "unique", "degrees", "append", "hypot",
    # …và nhóm numpy hay dùng mà vòng 1 bỏ sót
    "argsort", "average", "gradient", "ptp", "arctan", "arctan2", "arcsin",
    "arccos", "count_nonzero", "convolve", "isclose", "allclose", "roll",
    "nanpercentile", "nanquantile", "searchsorted", "greater_equal",
    "less_equal", "not_equal", "mod", "true_divide", "floor_divide",
    "square", "cbrt", "reciprocal", "take", "repeat", "ravel", "flatten",
    "reshape", "radians",
}
_MATH_SAFE = {
    "pi", "e", "tau", "inf", "nan", "sqrt", "log", "log2", "log10", "exp",
    "pow", "fabs", "floor", "ceil", "trunc", "isnan", "isinf", "isfinite",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "degrees",
    "radians", "hypot", "copysign", "fmod", "gcd", "factorial", "comb",
    "perm", "erf", "gamma", "sinh", "cosh", "tanh",
}


def _safe_globals(df: pd.DataFrame, params: dict) -> dict:
    return {
        "__builtins__": _safe_builtins(),
        "pd":     _make_safe_namespace("pd", pd, _PD_SAFE),
        "np":     _make_safe_namespace("np", np, _NP_SAFE),
        "math":   _make_safe_namespace("math", math, _MATH_SAFE),
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
    Windows). Code vẫn qua ĐỦ lưới AST + khay pd/np/math (import/open/dunder/
    module-traversal/ghi-file đều chặn), chỉ mất lưới TIMEOUT chống vòng lặp
    vô hạn. Use only when running many backtest windows where the mp overhead
    dominates.
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


class IsolatedExecutor(StrategyExecutor):
    """Option B (06/08/2026) — chạy code trong TIẾN TRÌNH ĐÃ KHOÁ NĂNG LỰC.

    Ba vòng red-team chứng minh lọc cú pháp trên pandas thật là đuổi bắt vô
    tận (xem vnstock_sandbox_runtime). Ở đây đổi cách đánh: worker gọi
    `lockdown()` — không mở được file, không gọi shell, không mở socket, và
    xoá sạch API key khỏi env — TRƯỚC khi chạm code chiến lược. `df.to_csv()`
    chết ở đúng bước ghi file, bất kể được gọi bằng cú pháp gì.

    MỘT worker phục vụ NHIỀU lần chạy (cache hàm signal đã compile theo code):
    backtest gọi hàng nghìn cửa sổ, spawn mỗi lần thì Windows tốn ~0.5s/lần —
    chính lý do bản cũ phải chạy in-process và mất luôn cách ly.

    Worker chết/timeout → giết, spawn lại ở lần gọi sau (tự lành).
    Tắt (chạy in-process như cũ): VNSTOCK_STRATEGY_ISOLATION=0.
    """

    def __init__(self, timeout_s: float = STRATEGY_TIMEOUT_S):
        self.timeout_s = timeout_s
        self._proc = None
        self._lock_stats: dict = {}
        self._spawn_error = ""
        self._warned = False
        self._fallback = InProcessExecutor(timeout_s, fast_mode=True)

    # ── vòng đời worker ───────────────────────────────────────────────
    def _spawn(self) -> bool:
        import subprocess
        from vnstock_sandbox_runtime import _recv, minimal_env
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "vnstock_sandbox_runtime"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=str(Path(__file__).resolve().parent),
                env=minimal_env(),          # KHÔNG kế thừa .env → không có key
            )
            hello = _recv(self._proc.stdout)   # worker báo sau khi lockdown
            if not (hello or {}).get("ready"):
                self._kill()
                return False
            self._lock_stats = (hello or {}).get("stats", {})
            return True
        except Exception as e:
            # Ghi LẠI lý do: `except Exception: return False` trần từng nuốt
            # mất một NameError của chính code này (thiếu `import sys`) và
            # âm thầm tụt về in-process — đúng kiểu hỏng nguy hiểm nhất.
            self._spawn_error = f"{type(e).__name__}: {str(e)[:160]}"
            self._kill()
            return False

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        for step in (proc.terminate, proc.kill):
            try:
                step()
                proc.wait(timeout=2)
                break
            except Exception:
                continue
        for stream in (getattr(proc, "stdin", None), getattr(proc, "stdout", None)):
            try:
                stream.close()
            except Exception:
                pass

    def _ensure(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        self._kill()
        return self._spawn()

    def shutdown(self) -> None:
        from vnstock_sandbox_runtime import _send
        if self._proc is not None and self._proc.poll() is None:
            try:
                _send(self._proc.stdin, {"stop": True})
                self._proc.wait(timeout=3)
            except Exception:
                pass
        self._kill()

    # ── chạy ──────────────────────────────────────────────────────────
    def run(self, code: str, df: pd.DataFrame, params: dict) -> dict:
        if not _isolation_enabled():
            return self._fallback.run(code, df, params)

        _validate_ast(code)        # lớp 1: bắt sớm, khỏi tốn một vòng IPC
        if not self._ensure():
            # Không dựng được worker — KHÔNG im lặng bỏ cách ly, phải kêu to.
            # Chỉ kêu MỘT lần/executor: backtest gọi hàng nghìn lần, in mỗi
            # lần thì log ngập và người đọc bỏ qua luôn cảnh báo thật.
            if not self._warned:
                self._warned = True
                print(f"[strategy] ⚠ không dựng được worker cách ly "
                      f"({self._spawn_error or 'không rõ'}) — chạy in-process "
                      f"(CHỈ CÒN lưới AST, yếu hơn hẳn). "
                      f"Tắt cảnh báo: VNSTOCK_STRATEGY_ISOLATION=0")
            return self._fallback.run(code, df, params)

        import pickle as _pkl
        from vnstock_sandbox_runtime import _recv, _send
        try:
            _send(self._proc.stdin,
                  {"code": code, "df": _pkl.dumps(df), "params": params})
            reply = _recv(self._proc.stdout)
        except Exception as e:
            self._kill()           # pipe hỏng → dựng worker mới ở lần sau
            raise RuntimeError(
                f"Strategy worker chết giữa chừng ({type(e).__name__})") from e
        if reply is None:
            self._kill()
            raise RuntimeError("Strategy worker đóng pipe không trả lời")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "unknown worker error"))
        return reply["result"]


def _isolation_enabled() -> bool:
    """Cách ly bật MẶC ĐỊNH. Kill-switch theo nếp repo — tắt thì lùi về
    in-process (chỉ còn lưới AST, yếu hơn hẳn)."""
    return (os.environ.get("VNSTOCK_STRATEGY_ISOLATION") or "1") \
        .strip().lower() not in ("0", "false", "off")


# Executor MẶC ĐỊNH từ 06/08/2026: tiến trình riêng đã khoá năng lực
# (Option B trong sơ đồ đầu file — nay đã có thật, không còn placeholder).
# MỘT worker phục vụ mọi lần gọi nên không còn đánh đổi tốc-độ-đổi-cách-ly
# như bản `fast_mode=True` cũ: spawn 1 lần thay vì ~0.5s mỗi cửa sổ.
# Tắt: VNSTOCK_STRATEGY_ISOLATION=0 (lùi về in-process, chỉ còn lưới AST).
EXECUTOR: StrategyExecutor = IsolatedExecutor()

# Trước đây "strict" nghĩa là spawn mỗi lần gọi (vẫn CÙNG quyền, nên thực ra
# không cách ly được gì — red-team 06/08 chứng minh nó dính y hệt bản fast).
# Nay cả hai trỏ về cùng một cơ chế cách ly thật; giữ tên cho tương thích.
STRICT_EXECUTOR: StrategyExecutor = EXECUTOR

# Worker là tiến trình CON qua subprocess — không tự chết theo cha như
# multiprocessing daemon. Không dọn thì mỗi lần chạy dashboard/pipeline để
# lại một tiến trình python treo.
import atexit as _atexit

_atexit.register(EXECUTOR.shutdown)


# ── Output schema validation ───────────────────────────────────────────────
def _validate_signal_output(out: dict) -> dict:
    """Coerce + validate the dict returned by signal().

    Pure type coercion — risk-target sanitization (clamp + tick rounding)
    happens later in `_sanitize_targets()` because it needs ticker context
    (warrants vs stocks have different sensible bands and tick sizes).
    """
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


# ── Risk-target sanitization (ticker-aware) ────────────────────────────────
def _is_warrant(ticker: str) -> bool:
    """Vietnamese covered warrants on HOSE: ticker like CFPT2517, CVHM2308.
    Pattern: starts with 'C', then 3-letter underlying, then 4 digits (YYNN).
    """
    if not ticker or len(ticker) < 7:
        return False
    t = ticker.upper()
    return t.startswith("C") and t[-4:].isdigit() and t[1:4].isalpha()


def _round_to_tick(price: float, ticker: str) -> float:
    """Round price to the nearest legal tick on HOSE.

    Prices are stored in nghìn đồng (thousand VND), so ticks are scaled:
      Stock < 10K VND      → 10 VND  → 0.01
      Stock 10K–49.95K VND → 50 VND  → 0.05
      Stock ≥ 50K VND      → 100 VND → 0.10
      Warrants (any price) → 10 VND  → 0.01
    """
    if price <= 0:
        return price
    if _is_warrant(ticker):
        tick = 0.01
    elif price < 10:
        tick = 0.01
    elif price < 50:
        tick = 0.05
    else:
        tick = 0.10
    return round(round(price / tick) * tick, 2)


def _sanitize_targets(
    action: str, entry: float, tp: float, sl: float, ticker: str
) -> tuple[float, float, bool]:
    """Clamp tp/sl into ticker-appropriate bands and snap to legal ticks.

    LLM-generated strategies sometimes emit bogus risk targets (e.g.
    tp = 10×entry, sl < 0). We preserve the action signal but force
    sane bounds so recs are tradable.

    Bands (5-day horizon):
      Stocks   — TP +5–10%, SL -3–7%   (default 7%/5%)
      Warrants — TP +15–30%, SL -8–15% (default 20%/12% — leveraged)

    Returns (tp_rounded, sl_rounded, was_clamped).
    """
    if entry <= 0 or action == "hold":
        return tp, sl, False

    if _is_warrant(ticker):
        tp_default, sl_default = 1.20, 0.88     # +20%, -12%
        tp_band   = (1.05, 1.50)                # accept +5% to +50%
        sl_band   = (0.60, 0.99)                # accept -1% to -40%
    else:
        tp_default, sl_default = 1.07, 0.95     # +7%, -5%
        tp_band   = (1.005, 1.30)               # accept +0.5% to +30%
        sl_band   = (0.70, 0.999)               # accept -0.1% to -30%

    clamped = False
    if action == "buy":
        if not (tp_band[0] <= tp / entry <= tp_band[1]):
            tp = entry * tp_default
            clamped = True
        if not (sl_band[0] <= sl / entry <= sl_band[1]):
            sl = entry * sl_default
            clamped = True
    elif action == "sell":
        # Mirror: for shorts tp < entry < sl
        if not (sl_band[0] <= tp / entry <= sl_band[1]):
            tp = entry * (2 - tp_default)       # symmetric
            clamped = True
        if not (tp_band[0] <= sl / entry <= tp_band[1]):
            sl = entry * (2 - sl_default)
            clamped = True

    return _round_to_tick(tp, ticker), _round_to_tick(sl, ticker), clamped


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


def _load_history_from_parquet(
    ticker: str, days: int, prices_dir: Path | None = None
) -> pd.DataFrame:
    """CLI-safe daily OHLCV read straight from the parquet warehouse.

    Mirrors vnstock_dashboard.load_price_history but without the @st.cache_data
    wrapper (which raises outside a Streamlit session). Units are normalised the
    same way the warehouse pipeline does so prices match recommendation targets.
    """
    root = Path(prices_dir) if prices_dir else Path("data_warehouse/prices")
    base = root / f"ticker={ticker.upper()}"
    if not base.exists():
        return pd.DataFrame()
    try:
        import pyarrow.parquet as _pq
    except Exception:
        return pd.DataFrame()
    frames = []
    for yd in sorted(base.glob("year=*")):
        for pf in yd.glob("*.parquet"):
            try:
                frames.append(_pq.read_table(
                    str(pf),
                    columns=["time", "open", "high", "low", "close", "volume"],
                ).to_pandas())
            except Exception:
                continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    if days > 0:
        df = df[df["time"] >= _dt.now() - _td(days=days)]
    df = df.sort_values("time").reset_index(drop=True)
    try:
        from vnstock_runner import _normalize_prices
        df = _normalize_prices(df)
    except Exception:
        pass
    return df


def _in_streamlit_session() -> bool:
    """True CHỈ khi đang chạy trong một Streamlit runtime thật."""
    try:
        from streamlit import runtime
        return bool(runtime.exists())
    except Exception:
        return False


def _load_history(ticker: str, days: int) -> pd.DataFrame:
    """Load recent daily OHLCV for a ticker.

    Inside a real Streamlit session → the dashboard's @st.cache_data loader
    (fast, shared cache). Everywhere else → direct parquet read. The runtime
    check matters twice over: (a) the cached loader FAILS outside a session on
    some setups — reconcile/backtest from CLI silently got empty frames,
    leaving graded recs stuck open as zombies; (b) on setups where bare mode
    "works", merely importing vnstock_dashboard EXECUTES the whole app at
    module level (st.pills nav, ~4k lines) — spams ScriptRunContext warnings
    and wastes seconds in every CLI run (seen live on vnstock_genetic 15/07).
    """
    if _in_streamlit_session():
        try:
            from vnstock_dashboard import load_price_history
            df = load_price_history(ticker, days=days)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    return _load_history_from_parquet(ticker, days)


# ── Chi phí giao dịch + thứ tự chạm TP/SL trong bar (DONE 2026-07-14, ý ──
# tưởng nautilus_trader FeeModel + bar_adaptive_high_low_ordering). Backtest
# pnl nay là NET sau phí round-trip; grading rec thật (vnstock_train) vẫn
# GROSS (không đổi convention DB) — gap decay vì thế hơi bảo thủ, chấp nhận.

_COST_ROUNDTRIP_PCT_DEFAULT = 0.4   # phí CTCK ~0.15%/chiều + thuế bán 0.1%


def _cost_roundtrip_pct() -> float:
    """Phí giao dịch round-trip (%) trừ vào pnl mỗi lệnh backtest.
    Tunable qua env VNSTOCK_COST_ROUNDTRIP_PCT (đặt 0 để về gross)."""
    try:
        return float(os.environ.get("VNSTOCK_COST_ROUNDTRIP_PCT",
                                    str(_COST_ROUNDTRIP_PCT_DEFAULT)))
    except (TypeError, ValueError):
        return _COST_ROUNDTRIP_PCT_DEFAULT


def _bar_high_first(bar) -> "bool | None":
    """Heuristic nautilus `bar_adaptive_high_low_ordering`: trong 1 bar,
    cực trị GẦN GIÁ MỞ CỬA hơn được coi là chạm TRƯỚC. True = high trước,
    False = low trước, None = không quyết được (thiếu/hỏng open) — caller
    fallback về phía SL (pessimistic, giữ nếp cũ)."""
    try:
        o = float(bar["open"])
        hi, lo = float(bar["high"]), float(bar["low"])
    except (KeyError, TypeError, ValueError):
        return None
    if math.isnan(o) or o <= 0:
        return None
    return abs(hi - o) < abs(lo - o)


def _simulate_trade(future: pd.DataFrame, sig: dict) -> tuple[float, str]:
    """Walk forward the next N bars. Return (pnl_pct NET sau phí, reason).

    Bar chứa CẢ TP lẫn SL → thứ tự theo `_bar_high_first` (cực trị gần open
    chạm trước); không quyết được → SL thắng (pessimistic như trước)."""
    entry = sig["entry"]
    tp    = sig["tp"]
    sl    = sig["sl"]
    if entry <= 0 or future.empty:
        return 0.0, "no_data"
    last = float(future["close"].iloc[-1])
    cost = _cost_roundtrip_pct()

    # Long-only for now (action=buy). action=sell handled symmetrically.
    if sig["action"] == "buy":
        for _, bar in future.iterrows():
            hi, lo = float(bar["high"]), float(bar["low"])
            sl_hit = sl > 0 and lo <= sl
            tp_hit = tp > 0 and hi >= tp
            if sl_hit and tp_hit:
                if _bar_high_first(bar):        # high (TP) chạm trước
                    return ((tp / entry) - 1) * 100 - cost, "tp"
                return ((sl / entry) - 1) * 100 - cost, "sl"
            if sl_hit:
                return ((sl / entry) - 1) * 100 - cost, "sl"
            if tp_hit:
                return ((tp / entry) - 1) * 100 - cost, "tp"
        return ((last / entry) - 1) * 100 - cost, "expire"
    if sig["action"] == "sell":
        for _, bar in future.iterrows():
            hi, lo = float(bar["high"]), float(bar["low"])
            sl_hit = sl > 0 and hi >= sl        # sell: SL phía TRÊN
            tp_hit = tp > 0 and lo <= tp        # sell: TP phía DƯỚI
            if sl_hit and tp_hit:
                if _bar_high_first(bar) is False:   # low (TP) chạm trước
                    return ((entry / tp) - 1) * 100 - cost, "tp"
                return ((entry / sl) - 1) * 100 - cost, "sl"
            if sl_hit:
                return ((entry / sl) - 1) * 100 - cost, "sl"
            if tp_hit:
                return ((entry / tp) - 1) * 100 - cost, "tp"
        return ((entry / last) - 1) * 100 - cost, "expire"
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
            "profit_factor": None,
            "recovery_factor": None,
            "errors":        errors[:20],
        }

    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak)
    pf, rf = profit_and_recovery(pnls)

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
        "profit_factor":   pf,
        "recovery_factor": rf,
        "exit_mix":     exit_mix(trades),
        "validation":   validate_backtest_quality(trades),
        "trades":       trades[:200],
        "errors":       errors[:20],
    }


def exit_mix(trades: "list[dict]") -> "dict[str, float]":
    """Tỷ lệ lệnh theo LÝ DO THOÁT: {"tp": …, "sl": …, "expire": …}.

    Lý do thoát đã được ghi vào TỪNG lệnh từ đầu (`_simulate_trade` trả
    "tp"/"sl"/"expire") nhưng chưa bao giờ được gom — nên win rate 45% che mất
    sự thật "0% lệnh chạm chốt lời, toàn hết hạn khi đang lãi nhẹ". User phải
    đợi 49 khuyến nghị THẬT qua nhiều tuần mới thấy điều mà mọi backtest tính
    ra được ngay (phát hiện 13/08). Một chiến lược tp≈0 là TP đặt ngoài tầm
    với của horizon — chết từ thiết kế, bất kể p-value đẹp cỡ nào.
    """
    reasons = [t.get("reason") for t in trades if t.get("reason")]
    if not reasons:
        return {}
    n = len(reasons)
    return {r: round(reasons.count(r) / n, 3) for r in sorted(set(reasons))}


def profit_and_recovery(pnls: "np.ndarray") -> tuple:
    """profit_factor = Σlãi / |Σlỗ| · recovery_factor = net / |max drawdown|.

    2 thống kê xác nhận lại từ khảo sát StockSharp Algo/Statistics
    (ProfitFactor/RecoveryFactor — đã ghi nhận từ nautilus trước đó).
    Mẫu suy biến trả None thay vì chia 0: không có lệnh lỗ → profit_factor
    None (không phải ∞ — JSON-safe); equity không có drawdown →
    recovery_factor None."""
    pnls = np.asarray(pnls, dtype=float)
    if pnls.size == 0:
        return None, None
    gross_profit = float(pnls[pnls > 0].sum())
    gross_loss = float(pnls[pnls < 0].sum())
    pf = float(gross_profit / abs(gross_loss)) if gross_loss < 0 else None

    cum = np.cumsum(pnls)
    # Drawdown tính từ MỐC VỐN BAN ĐẦU (baseline 0 cũng là một đỉnh) — chuỗi
    # toàn lỗ có maxDD = |net|, khác metric max_drawdown hiện hành (đỉnh đầu
    # là cum[0]); giữ metric cũ nguyên trạng, chỉ recovery dùng bản chuẩn.
    peak = np.maximum.accumulate(np.concatenate(([0.0], cum)))[1:]
    max_dd = float((cum - peak).min())
    rf = float(cum[-1] / abs(max_dd)) if max_dd < 0 else None
    return pf, rf


# ── Kiểm định thống kê chống-ăn-may (DONE 2026-07-14, ý tưởng từ khảo sát ──
# HKUDS/Vibe-Trading agent/backtest/validation.py). Numpy thuần, zero
# dependency, deterministic (seed cố định). LƯU Ý so với bản gốc: họ xáo THỨ
# TỰ pnl rồi đo path-metrics; Sharpe per-trade của mình (mean/std các pnl) là
# BẤT BIẾN với thứ tự → permutation-thứ-tự vô nghĩa ở đây. Thay bằng
# SIGN-FLIP permutation chuẩn: H0 = pnl đối xứng quanh 0 (không có edge) →
# lật dấu ngẫu nhiên từng lệnh, đếm tỷ lệ mô phỏng có Sharpe ≥ thực.

_MC_SIMS = 1000
_MC_PVALUE_MAX = 0.10          # p ≥ ngưỡng → không đủ bằng chứng hơn ăn-may
_BOOT_SIMS = 1000
_BOOT_CI = 0.90                # CI 90% cho Sharpe (percentile bootstrap)
_WF_FOLDS = 4
_WF_MIN_POSITIVE_FRAC = 0.5    # ≥ nửa số cửa sổ thời gian phải dương
# Chốt lời phải VỚI TỚI ĐƯỢC: dưới tỷ lệ này lệnh chạm TP → TP nằm ngoài tầm
# với của horizon (ca thật 13/08: 0/49 khuyến nghị live chạm TP, 35 hết hạn —
# TP 2.5-4×ATR không thể tới trong 5 phiên, còn SL 1.5-2.5×ATR nằm gọn trong
# nhiễu). Cần đủ lệnh ĐÃ ĐÓNG mới dám kết luận — không đo được ≠ đo ra xấu.
_TP_REACH_MIN_SHARE = 0.05
_TP_REACH_MIN_CLOSED = 20


def monte_carlo_pvalue(pnls: "np.ndarray", n_sim: int = _MC_SIMS,
                       seed: int = 42) -> "float | None":
    """p-value sign-flip permutation cho Sharpe per-trade > 0.

    H0: chiến lược không có edge — pnl mỗi lệnh đối xứng quanh 0. Lật dấu
    ngẫu nhiên từng pnl ``n_sim`` lần; p = tỷ lệ mô phỏng đạt Sharpe ≥ thực
    (cộng 1 hiệu chỉnh để p không bao giờ = 0). None khi < 3 lệnh/không σ."""
    pnls = np.asarray(pnls, dtype=float)
    if len(pnls) < 3 or pnls.std() == 0:
        return None
    actual = pnls.mean() / pnls.std()
    rng = np.random.default_rng(seed)
    signs = rng.choice((-1.0, 1.0), size=(n_sim, len(pnls)))
    sims = signs * np.abs(pnls)
    stds = sims.std(axis=1)
    stds[stds == 0] = np.inf
    sim_sharpes = sims.mean(axis=1) / stds
    return float((np.sum(sim_sharpes >= actual) + 1) / (n_sim + 1))


def bootstrap_sharpe_ci(pnls: "np.ndarray", n_boot: int = _BOOT_SIMS,
                        seed: int = 42,
                        ci: float = _BOOT_CI) -> "tuple[float, float] | None":
    """CI percentile cho Sharpe per-trade (resample có hoàn lại) — trả
    (lo, hi); lo > 0 nghĩa là edge không phụ thuộc vài lệnh vàng."""
    pnls = np.asarray(pnls, dtype=float)
    if len(pnls) < 3:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pnls), size=(n_boot, len(pnls)))
    samples = pnls[idx]
    stds = samples.std(axis=1)
    stds[stds == 0] = np.inf
    sharpes = samples.mean(axis=1) / stds
    alpha = (1 - ci) / 2
    return (float(np.quantile(sharpes, alpha)),
            float(np.quantile(sharpes, 1 - alpha)))


def walk_forward_consistency(trades: list[dict],
                             n_folds: int = _WF_FOLDS) -> "dict | None":
    """Chia lệnh THEO THỜI GIAN (start_idx của cửa sổ backtest) thành
    ``n_folds`` đoạn — hiệu năng có đều không hay dồn vào 1 giai đoạn?
    Trả {n_folds, positive_frac, fold_pnls}; None khi ít lệnh hơn số fold."""
    if len(trades) < n_folds:
        return None
    ordered = sorted(trades, key=lambda t: t.get("start_idx", 0))
    pnls = np.asarray([t["pnl"] for t in ordered], dtype=float)
    folds = np.array_split(pnls, n_folds)
    fold_pnls = [float(f.sum()) for f in folds]
    positive = sum(1 for f in fold_pnls if f > 0)
    return {"n_folds": n_folds,
            "positive_frac": round(positive / n_folds, 2),
            "fold_pnls": [round(f, 2) for f in fold_pnls]}


def validate_backtest_quality(trades: list[dict]) -> "dict | None":
    """Chạy cả 3 kiểm định trên list trades của backtest → {p_value_sharpe,
    sharpe_ci, walk_forward, passed, reasons}. ``passed`` = p-value dưới
    ngưỡng VÀ ≥ nửa cửa sổ walk-forward dương (CI chỉ để tham khảo — không
    gate vì mẫu nhỏ hay cho CI rộng). None khi < 3 lệnh (gate n_trades của
    vòng validate đã chặn trước)."""
    if not trades or len(trades) < 3:
        return None
    pnls = np.asarray([t["pnl"] for t in trades], dtype=float)
    p = monte_carlo_pvalue(pnls)
    ci = bootstrap_sharpe_ci(pnls)
    wf = walk_forward_consistency(trades)
    reasons: list[str] = []
    if p is not None and p >= _MC_PVALUE_MAX:
        reasons.append(f"p-value {p:.3f} ≥ {_MC_PVALUE_MAX} — Sharpe không hơn ăn-may")
    if wf is not None and wf["positive_frac"] < _WF_MIN_POSITIVE_FRAC:
        reasons.append(f"chỉ {wf['positive_frac']:.0%} cửa sổ thời gian dương "
                       f"— hiệu năng dồn cục, không bền")
    # Cổng "chốt lời phải với tới được" (13/08). Chỉ đếm lệnh ĐÃ ĐÓNG
    # (tp/sl/expire) — "hold" không nói gì về tầm với của TP.
    _closed = [t.get("reason") for t in trades
               if t.get("reason") in ("tp", "sl", "expire")]
    if len(_closed) >= _TP_REACH_MIN_CLOSED:
        _tp_share = _closed.count("tp") / len(_closed)
        if _tp_share < _TP_REACH_MIN_SHARE:
            reasons.append(
                f"chỉ {_tp_share:.0%} lệnh chạm chốt lời "
                f"({_closed.count('expire')}/{len(_closed)} hết hạn) — "
                f"TP nằm ngoài tầm với của horizon, R:R trên giấy không thực hiện được")
    return {
        "p_value_sharpe": p,
        "sharpe_ci": list(ci) if ci else None,
        "walk_forward": wf,
        "passed": not reasons,
        "reasons": reasons,
    }


def _validation_ok(metrics: dict) -> bool:
    """Gate helper: passed của bộ kiểm định. TRUE khi vắng validation —
    backtest cũ (trước 2026-07-14) hoặc quá ít lệnh, các trường hợp đó gate
    n_trades/expectancy hiện hành đã xử."""
    v = metrics.get("validation")
    return True if not v else bool(v.get("passed"))


def apply_selection_penalty(metrics: dict, n_trials: int) -> dict:
    """Hiệu chỉnh ĐA-THỬ-NGHIỆM kiểu Bonferroni cho winner-of-N (ý tưởng từ
    khảo sát ML4T 3rd ed chương Factor Zoo, 2026-07-15: "selecting the best
    inflates estimates"). Mỗi vòng revise/tune/cold-start backtest N ứng
    viên rồi CHỌN BEST → p-value của winner bị lạm phát do selection bias,
    tích lũy qua các vòng train hàng ngày (rule 2b).

    p_adj = min(1, p × n_trials); p_adj vượt ngưỡng → passed=False kèm lý
    do. CHỈ SIẾT, không nới: p_adj dưới ngưỡng không lật passed thành True
    (walk-forward có thể đã đánh trượt). Mutate + trả metrics; no-op khi
    n_trials ≤ 1 / thiếu validation / thiếu p."""
    v = (metrics or {}).get("validation")
    if not v or n_trials <= 1:
        return metrics
    p = v.get("p_value_sharpe")
    if p is None:
        return metrics
    p_adj = min(1.0, p * n_trials)
    v["n_trials"] = n_trials
    v["p_value_adj"] = round(p_adj, 6)
    if p_adj >= _MC_PVALUE_MAX and v.get("passed"):
        v["passed"] = False
        v.setdefault("reasons", []).append(
            f"p hiệu chỉnh chọn-lọc {p_adj:.3f} (p {p:.3f} × {n_trials} ứng viên) "
            f"≥ {_MC_PVALUE_MAX} — thắng cuộc thi nội bộ chưa đủ bằng chứng edge")
    return metrics


# ── Vòng đời decay chiến lược (DONE 2026-07-14, cùng khảo sát Vibe-Trading) ─
# Backtest nói chiến lược tốt nhưng LỆNH THẬT (rec đã đóng qua reconciler) tụt
# xa → tự demote khỏi active để strategy_loop kế tiếp cold-start bản mới.
# Trạng thái TÍNH TOÁN mỗi lần gọi (healthy/monitoring/decayed/insufficient);
# chỉ transition "decayed" được ghi DB (status='decayed' — get_active_family
# lọc status='active' nên bản decayed tự rơi khỏi vòng tune/revise).

_DECAY_MIN_LIVE_N = 8          # cần ≥ N rec đóng THẬT mới dám kết luận
_DECAY_WR_GAP = 0.25           # backtest_wr − live_wr ≥ 25 điểm % → decayed
_MONITOR_WR_GAP = 0.12         # ≥ 12 điểm % → monitoring (cảnh báo, chưa demote)
_DECAY_LIVE_WR_FLOOR = 0.30    # live wr ≤ 30% VÀ avg pnl âm → decayed dù gap nhỏ


def strategy_health(strategy_id: int) -> dict:
    """So win-rate LỆNH THẬT (rec_outcomes, bỏ superseded) với win-rate
    backtest gần nhất → {state, live_n, live_win_rate, backtest_win_rate,
    gap, reasons}. state ∈ insufficient/healthy/monitoring/decayed."""
    live = mem.recommendation_performance(strategy_id)
    bt = mem.latest_backtest(strategy_id) or {}
    bt_wr = bt.get("win_rate")
    n = int(live.get("n") or 0)
    out = {"state": "insufficient", "live_n": n,
           "live_win_rate": live.get("win_rate"),
           "backtest_win_rate": bt_wr, "gap": None, "reasons": []}
    if n < _DECAY_MIN_LIVE_N or bt_wr is None:
        return out
    live_wr = float(live["win_rate"])
    gap = float(bt_wr) - live_wr
    out["gap"] = round(gap, 3)
    if gap >= _DECAY_WR_GAP:
        out["state"] = "decayed"
        out["reasons"].append(
            f"win-rate thật {live_wr:.0%} tụt {gap * 100:.0f} điểm % so với "
            f"backtest {float(bt_wr):.0%} (n={n})")
    elif live_wr <= _DECAY_LIVE_WR_FLOOR and float(live.get("avg_pnl") or 0) < 0:
        out["state"] = "decayed"
        out["reasons"].append(
            f"win-rate thật {live_wr:.0%} ≤ {_DECAY_LIVE_WR_FLOOR:.0%} và "
            f"PnL trung bình âm ({float(live.get('avg_pnl') or 0):+.2f}%, n={n})")
    elif gap >= _MONITOR_WR_GAP:
        out["state"] = "monitoring"
        out["reasons"].append(
            f"win-rate thật {live_wr:.0%} kém backtest {gap * 100:.0f} điểm % "
            f"— theo dõi, chưa demote")
    else:
        out["state"] = "healthy"
    return out


def check_strategy_decay(apply: bool = True) -> "dict | None":
    """Đánh giá sức khỏe chiến lược active; state=decayed và ``apply`` →
    demote (status='decayed') để lần train sau cold-start bản mới. Zero LLM,
    chỉ SQL — an toàn gọi sau mỗi lần reconciler đóng rec. Trả report hoặc
    None (không có active / kill switch VNSTOCK_STRATEGY_DECAY=0)."""
    if os.environ.get("VNSTOCK_STRATEGY_DECAY", "1") == "0":
        return None
    active = mem.get_active_family()
    if not active:
        return None
    health = strategy_health(active["id"])
    report = {"strategy_id": active["id"], "name": active.get("name"),
              "applied": False, **health}
    if health["state"] == "decayed" and apply:
        mem.update_strategy_status(active["id"], "decayed")
        report["applied"] = True
    return report


# ── Khối lượng gợi ý fixed-risk (DONE 2026-07-14, ý tưởng nautilus ─────────
# FixedRiskSizer): qty = (NAV × risk%) / (rủi ro/cp + phí/cp), tròn XUỐNG lô
# 100, cap giá trị lệnh ≤ max_position_pct × NAV. DISPLAY-ONLY — không ghi
# DB, không đổi hành vi rec; chưa cấu hình NAV thì mọi chỗ hiển thị im lặng.

_SIZING_CONFIG = Path("data_warehouse/_meta/sizing_config.json")
_LOT_SIZE = 100
_SIZING_DEFAULTS = {"nav_million": None, "risk_pct": 1.0,
                    "max_position_pct": 25.0, "max_adv_pct": 10.0}


def load_sizing_config() -> dict:
    """Config sizing của user (NAV triệu đồng / % rủi ro mỗi lệnh / % NAV
    tối đa 1 lệnh). Thiếu file/hỏng → defaults với nav_million=None (tắt)."""
    cfg = dict(_SIZING_DEFAULTS)
    try:
        raw = json.loads(_SIZING_CONFIG.read_text(encoding="utf-8"))
        for k in cfg:
            if raw.get(k) is not None:
                cfg[k] = float(raw[k])
    except (OSError, ValueError, TypeError):
        pass
    if cfg.get("nav_million") is not None and cfg["nav_million"] <= 0:
        cfg["nav_million"] = None
    return cfg


def save_sizing_config(nav_million=None, risk_pct=None,
                       max_position_pct=None, max_adv_pct=None) -> dict:
    """Ghi config sizing (atomic tmp+replace, mirror allocation_state).
    Chỉ field truyền vào được đổi; trả config sau khi ghi."""
    cfg = load_sizing_config()
    if nav_million is not None:
        cfg["nav_million"] = float(nav_million) if float(nav_million) > 0 else None
    if risk_pct is not None and float(risk_pct) > 0:
        cfg["risk_pct"] = float(risk_pct)
    if max_position_pct is not None and float(max_position_pct) > 0:
        cfg["max_position_pct"] = float(max_position_pct)
    if max_adv_pct is not None and float(max_adv_pct) > 0:
        cfg["max_adv_pct"] = float(max_adv_pct)
    _SIZING_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SIZING_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, _SIZING_CONFIG)
    return cfg


def suggest_position_size(entry: float, sl: float, nav_million=None,
                          risk_pct=None,
                          adv_shares: "float | None" = None) -> "dict | None":
    """Khối lượng gợi ý theo rủi ro cố định. Giá vào theo NGHÌN đồng (như
    mọi giá trong hệ). None khi: chưa cấu hình NAV, entry/SL không hợp lệ
    (SL phải DƯỚI entry — rec là lệnh mua), hoặc qty < 1 lô.

    ``adv_shares`` (KLGD trung bình/ngày, cổ phiếu) → CAP THANH KHOẢN
    (ý tưởng zipline VolumeShareSlippage, khảo sát 15/07): qty ≤
    ``max_adv_pct`` (10%) × ADV — NAV lớn + mã mỏng mà gợi ý vượt xa khối
    lượng ngày là con số bất khả thi (tự đẩy giá khi mua thật)."""
    cfg = load_sizing_config()
    nav = float(nav_million) if nav_million else cfg.get("nav_million")
    risk = float(risk_pct) if risk_pct else cfg.get("risk_pct") or 1.0
    if not nav or nav <= 0:
        return None
    try:
        entry = float(entry)
        sl = float(sl)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or sl <= 0 or sl >= entry:
        return None

    nav_vnd = nav * 1e6
    risk_money = nav_vnd * risk / 100.0
    risk_per_share = (entry - sl) * 1000.0            # nghìn đồng → đồng
    fee_per_share = entry * 1000.0 * _cost_roundtrip_pct() / 100.0
    qty = int(risk_money / (risk_per_share + fee_per_share))

    # Cap giá trị lệnh — SL sát entry cho qty khổng lồ nhưng không thể dồn
    # cả NAV vào 1 mã (rủi ro gap qua đêm không có SL nào đỡ).
    max_pos_vnd = nav_vnd * (cfg.get("max_position_pct") or 25.0) / 100.0
    capped = False
    if qty * entry * 1000.0 > max_pos_vnd:
        qty = int(max_pos_vnd / (entry * 1000.0))
        capped = True

    # Cap thanh khoản: qty ≤ max_adv_pct × ADV
    capped_adv = False
    try:
        adv = float(adv_shares) if adv_shares else None
    except (TypeError, ValueError):
        adv = None
    if adv and adv > 0:
        liq_cap = int(adv * (cfg.get("max_adv_pct") or 10.0) / 100.0)
        if qty > liq_cap:
            qty = liq_cap
            capped_adv = True

    qty = (qty // _LOT_SIZE) * _LOT_SIZE              # tròn XUỐNG lô 100
    if qty < _LOT_SIZE:
        return None
    return {"qty": qty,
            "value_million": round(qty * entry * 1000.0 / 1e6, 1),
            "risk_pct": risk, "nav_million": nav,
            "capped": capped, "capped_adv": capped_adv}


def unrealized_pnl_pct(entry, last, action: str = "buy") -> "float | None":
    """Lãi/lỗ TẠM TÍNH (%) của rec đang mở theo giá close mới nhất — GROSS,
    display-only (mirror live mark-to-market của AI-Trader leaderboard,
    khảo sát 2026-07-15). None khi giá không hợp lệ."""
    try:
        entry = float(entry)
        last = float(last)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or last <= 0:
        return None
    pct = (last / entry - 1) * 100
    return -pct if str(action).lower() == "sell" else pct


_TRAIL_PCT_DEFAULT = 5.0


def trailing_stop_hint(sl, closes_since_entry,
                       trail_pct: float = _TRAIL_PCT_DEFAULT) -> "float | None":
    """SL TRAILING đề xuất cho rec MUA đang mở (mirror
    TrailingStopRiskManagementModel của QuantConnect/Lean, khảo sát 15/07):
    đỉnh close kể từ ngày mở × (1 − trail_pct%) — nâng SL theo đà lãi để
    khóa lợi nhuận. CHỈ trả giá trị khi cao hơn SL gốc một cách có nghĩa
    (> +0.5%); display-only — reconciler VẪN chấm theo SL gốc trong DB."""
    try:
        sl = float(sl)
        peaks = [float(c) for c in closes_since_entry if c and float(c) > 0]
    except (TypeError, ValueError):
        return None
    if not peaks:
        return None
    trail = max(peaks) * (1 - trail_pct / 100.0)
    if sl > 0 and trail <= sl * 1.005:
        return None                       # chưa vượt SL gốc đáng kể → khỏi gợi ý
    return round(trail, 2)


def psar_stop_hint(sl, highs, lows, closes=None) -> "float | None":
    """SL trailing THÍCH ỨNG theo Parabolic SAR (khảo sát je-suis-tm/
    quant-trading 15/07): khác bản 5% cố định, PSAR tăng tốc theo trend
    (AF equity 0.01) nên bám đà chặt dần khi trend kéo dài. CHỈ trả mức
    khi PSAR đang uptrend (SAR dưới giá) VÀ cao hơn SL gốc > +0.5% —
    cùng luật với `trailing_stop_hint`; display-only, reconciler VẪN
    chấm theo SL gốc trong DB. Rec SELL không áp dụng (caller đã lọc)."""
    try:
        sl = float(sl)
        from vnstock_indicators import parabolic_sar
        res = parabolic_sar(highs, lows, closes)
    except Exception:
        return None
    if not res:
        return None
    sar, trend = res
    if trend <= 0 or not sar or sar <= 0:
        return None
    if sl > 0 and sar <= sl * 1.005:
        return None
    return round(float(sar), 2)


# ── Strategy generation via agents ─────────────────────────────────────────
_STRATEGY_PROMPT = """\
Bạn là quant developer cho thị trường chứng khoán Việt Nam (T+2.5, không short, \
tick size 10/50/100 VND). Hãy viết MỘT chiến lược giao dịch ngắn hạn (horizon 5 ngày).

Output BẮT BUỘC theo đúng format (không markdown wrapper):

PARAMS:
{{"key1": value1, "key2": value2, ...}}

CODE:
def signal(df, params):
    ...

═══════════════════════════════════════════════════════════════
CONTRACT
═══════════════════════════════════════════════════════════════
- Hàm: def signal(df, params) -> dict
- df có cột: time, open, high, low, close, volume (mới nhất ở cuối, ~60 bars)
- Trả về dict:
    {{"action": "buy"|"sell"|"hold",
      "entry": float,        # giá tuyệt đối VND (KHÔNG phải %)
      "tp": float,           # take-profit absolute price
      "sl": float,           # stop-loss absolute price
      "confidence": 0..1}}   # CALIBRATED — xem mục QUALITY bên dưới
- Chỉ dùng: pd, np, math (có sẵn trong scope — là bản RÚT GỌN chỉ gồm hàm \
tính toán, không có submodule như pd.io)
- KHÔNG: import, open, exec, eval, file IO, network, os, sys, getattr/setattr
- KHÔNG dùng method ghi/đọc file hay thực thi chuỗi của DataFrame \
(df.to_csv/to_pickle/to_json/query/eval/plot) — sandbox từ chối cả bài
- Chỉ dùng API tính toán thông dụng (rolling/ewm/mean/std/shift/iloc/clip/\
diff/abs/quantile/np.where…); API lạ có thể bị sandbox từ chối
- Mọi ngưỡng (period, threshold, %) PHẢI đọc từ params để có thể tune

═══════════════════════════════════════════════════════════════
YÊU CẦU CHẤT LƯỢNG (non-trivial — đừng chỉ MA crossover thuần)
═══════════════════════════════════════════════════════════════

1) **CONFLUENCE (2-3 confirmation, không stack quá nhiều)**:
   Entry buy nên có 2-3 trong số sau cùng đồng thuận:
   - Trend: close > MA(n_trend) HOẶC MA ngắn cắt lên MA dài
   - Momentum: RSI vừa thoát vùng oversold (RSI[t-1]<35 và RSI[t]>RSI[t-1])
     HOẶC MACD histogram chuyển dương
   - Volume: volume[t] > k * avg_volume[20] (xác nhận lực mua)
   - Volatility filter: ATR/close không quá cao (tránh whipsaw)
   - Pullback entry: close gần MA20 từ trên xuống (mean reversion trong uptrend)

2) **REGIME FILTER (BẮT BUỘC — bỏ qua nếu thị trường không phù hợp)**:
   - Tính slope MA50 (hoặc tương tự): nếu slope âm và params.get('regime_filter', True) → return hold
   - HOẶC: nếu volatility (ATR%/close) > params['max_vol_pct'] → return hold (thị trường quá hỗn loạn)

3) **ATR-BASED STOPS (không dùng % cứng)**:
   - Tính ATR(14) hoặc rolling std của (high-low)
   - sl = entry - params['sl_atr_mult'] * ATR   (mặc định 1.5-2.5)
   - tp = entry + params['tp_atr_mult'] * ATR   (mặc định 2.5-4.0, đảm bảo R:R ≥ 1.5)
   - Nếu thị trường VN tick 50/100 VND → KHÔNG cần round, sandbox sẽ làm

4) **CONFIDENCE CALIBRATION (không hardcode 0.7)**:
   confidence phải PHẢN ÁNH chất lượng signal. Ví dụ:
     base = 0.4
     if confluence_count >= 3: base += 0.2
     if volume_ratio > 1.5: base += 0.1
     if rsi_in_sweet_spot: base += 0.1
     confidence = min(0.95, base)
   → confidence cao = setup đẹp, thấp = setup yếu (giúp emit_recommendations
     ưu tiên signal mạnh).

5) **ENTRY PRICE THỰC TẾ**:
   - entry = close hiện tại HOẶC pullback target gần (close * 0.99)
   - Không entry = high của bar (không khả thi)

═══════════════════════════════════════════════════════════════
TRÁNH ĐIỀU KIỆN MÂU THUẪN (lý do strategy thường ra 0 trades)
═══════════════════════════════════════════════════════════════
- ❌ SAI: RSI < 30 (giá đang giảm) VÀ close > MA20 (giá trên MA) → hiếm xảy ra
- ✅ ĐÚNG: RSI thoát oversold (RSI[t-1]<35 và RSI[t]>40) VÀ close > MA20 → momentum reversal có xác nhận trend
- ✅ ĐÚNG: MA10 cắt lên MA20 + volume[t] > 1.3*avg_vol → breakout với volume xác nhận
- Chiến lược PHẢI sinh ra ít nhất 8-15 tín hiệu trên window 60 ngày × 5 tickers VN30
- Điều kiện AND không quá 4 — mỗi AND giảm số signal theo hàm mũ

═══════════════════════════════════════════════════════════════
EXAMPLE STRUCTURE (không copy nguyên si — viết mới phù hợp)
═══════════════════════════════════════════════════════════════
def signal(df, params):
    if len(df) < 50:
        return {{"action": "hold", "entry": 0, "tp": 0, "sl": 0, "confidence": 0}}
    close = df['close'].astype(float)
    high  = df['high'].astype(float)
    low   = df['low'].astype(float)
    vol   = df['volume'].astype(float)

    # Indicators
    ma_short = close.rolling(params['ma_short']).mean()
    ma_long  = close.rolling(params['ma_long']).mean()
    delta = close.diff()
    up = delta.clip(lower=0).ewm(com=13).mean()
    dn = (-delta).clip(lower=0).ewm(com=13).mean()
    rsi = 100 - 100/(1 + up/dn.replace(0, np.nan))
    tr  = pd.concat([(high-low), (high-close.shift()).abs(),
                     (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(params['atr_period']).mean()
    avg_vol = vol.rolling(20).mean()

    last = -1
    c, h, l = float(close.iloc[last]), float(high.iloc[last]), float(low.iloc[last])
    a = float(atr.iloc[last]) if not pd.isna(atr.iloc[last]) else c * 0.02

    # Regime filter — slope of MA_long
    ma_long_slope = (ma_long.iloc[last] - ma_long.iloc[last-5]) / max(ma_long.iloc[last-5], 1e-9)
    if params.get('regime_filter', True) and ma_long_slope < params['min_slope']:
        return {{"action": "hold", "entry": c, "tp": 0, "sl": 0, "confidence": 0.0}}

    # Confluence checks
    conf_trend    = c > ma_short.iloc[last] and ma_short.iloc[last] > ma_long.iloc[last]
    conf_momentum = (rsi.iloc[last-1] < params['rsi_oversold_exit']
                     and rsi.iloc[last] > rsi.iloc[last-1])
    conf_volume   = vol.iloc[last] > params['vol_mult'] * avg_vol.iloc[last]
    confluence = sum([conf_trend, conf_momentum, conf_volume])

    if confluence >= 2:
        entry = c
        sl    = entry - params['sl_atr_mult'] * a
        tp    = entry + params['tp_atr_mult'] * a
        confidence = min(0.95, 0.4 + 0.15 * confluence + (0.1 if conf_volume else 0))
        return {{"action": "buy", "entry": entry, "tp": tp, "sl": sl,
                "confidence": confidence}}
    return {{"action": "hold", "entry": c, "tp": 0, "sl": 0, "confidence": 0.0}}

PARAMS gợi ý (TỰ CHỌN giá trị, không copy):
{{"ma_short": 10, "ma_long": 20, "rsi_oversold_exit": 40, "vol_mult": 1.2,
  "atr_period": 14, "sl_atr_mult": 2.0, "tp_atr_mult": 3.0, "min_slope": -0.005,
  "regime_filter": true}}

═══════════════════════════════════════════════════════════════
Bối cảnh hiện tại:
{context}

{prior_feedback}

Output ĐÚNG 2 phần: dòng `PARAMS:` + JSON dict 1 dòng, sau đó dòng `CODE:` + Python pure.
KHÔNG markdown ```python ``` wrapper. KHÔNG comment thừa thãi trong code.
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

═══════════════════════════════════════════════════════════════
HÃY VIẾT LẠI CORE CODE — đổi cách tiếp cận hoàn toàn
═══════════════════════════════════════════════════════════════

CONTRACT: def signal(df, params) -> dict
  df: cột time, open, high, low, close, volume (~60 bars)
  return: {{"action": "buy"|"sell"|"hold", "entry": float, "tp": float, "sl": float, "confidence": 0..1}}
  Chỉ dùng pd, np, math. KHÔNG import/IO/network.

QUAN TRỌNG — Tránh lỗi phổ biến gây 0 trades:
- KHÔNG stack quá nhiều điều kiện AND (>4 AND → 0 trades)
- KHÔNG dùng điều kiện mâu thuẫn: RSI<30 VÀ close>MA20 → hiếm gặp
- PHẢI sinh ít nhất 8-15 tín hiệu buy trên window 60 ngày × 5 tickers VN30

YÊU CẦU CHẤT LƯỢNG (nếu approach trước thiếu):
1) **Confluence 2-3 confirmation** (trend + momentum + volume), không hardcode
2) **Regime filter**: slope MA50 hoặc volatility filter — return hold khi không phù hợp
3) **ATR-based stops**: sl = entry - sl_atr_mult * ATR; tp = entry + tp_atr_mult * ATR (R:R ≥ 1.5)
4) **Confidence calibration**: phản ánh chất lượng signal (0.4 base + bonus theo confluence count)
5) **Entry thực tế**: entry = close hoặc pullback gần, KHÔNG phải high của bar

Cách tiếp cận thay thế GỢI Ý (chọn 1, khác approach trước):
- Mean reversion: Bollinger lower band + RSI oversold exit + volume spike
- Momentum breakout: Donchian channel high break + volume confirmation + ATR filter
- Trend pullback: MA20 holds + RSI bounces from 40 + close > MA50
- Volatility contraction: ATR thấp + Bollinger squeeze + volume breakout

Output ĐÚNG 2 phần (KHÔNG markdown wrapper):
PARAMS:
{{"key": value, ...}}

CODE:
def signal(df, params):
    ...
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


def _reachability_hint(horizon_days: int) -> str:
    """Neo TP/SL của prompt sinh chiến lược vào SỐ ĐO thay vì con số bịa.

    Đọc `_meta/reachability.json` (user chạy `vnstock_reachability` trên máy
    thật). Vì sao phải neo: hướng dẫn cũ "tp_atr_mult 2.5-4.0" viết chung cho
    mọi horizon, mà đo 13/08 cho thấy ở 5 phiên TP 2.5×ATR chỉ với tới 16% số
    lần → 0/49 khuyến nghị live chạm chốt lời. Best-effort: thiếu file/thiếu
    horizon → chuỗi rỗng, prompt như cũ (không đo được thì không bịa neo).
    """
    try:
        blob = json.loads(Path("data_warehouse/_meta/reachability.json")
                          .read_text(encoding="utf-8"))
        s = (blob.get("summary") or {}).get(str(int(horizon_days)))
        if not s:
            return ""
        p60 = float(s["mfe_atr"]["p60"])
        reach = float(s["tp_reach_share"]["2.5"])
        return (
            f"\nĐO THỰC trên kho giá ({blob.get('generated_at', '?')[:10]}, "
            f"{blob.get('tickers_measured', '?')} mã): trong {int(horizon_days)} phiên, "
            f"p60 của mức lãi tối đa = {p60:.2f}×ATR; TP đặt 2.5×ATR chỉ với tới "
            f"{reach:.0%} số lần. Chọn tp_atr_mult quanh {p60:.1f} (±0.5) để TP "
            f"với tới được ~40-60% số lần — TUYỆT ĐỐI KHÔNG đặt TP xa hơn mức "
            f"giá thực sự đi được trong horizon này."
        )
    except Exception:
        return ""


def generate_strategy(
    agent,
    context_summary: str = "",
    prior_feedback: str = "",
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> tuple[str, dict, str | None]:
    """Ask an agent to generate a fresh strategy. Returns (code, params, error)."""
    _ctx = (context_summary or "Thị trường VN, large-cap, daily timeframe.")
    _ctx += (f"\nHorizon giữ lệnh: {int(horizon_days)} phiên — TP/SL phải với "
             f"tới được trong đúng ngần ấy phiên.")
    _ctx += _reachability_hint(horizon_days)
    prompt = _STRATEGY_PROMPT.format(
        context=_ctx,
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
    # Rule 2b: expectancy NET ≤ 0 → core vô giá trị sau phí, revise ngay
    # thay vì tune chờ hết tuần (15/07: family-05f9d495 lộ +0.365 gross →
    # −0.777 net + trượt kiểm định 🎲 — để nó "được tune" cả tuần là vô nghĩa,
    # phải cho các agent viết lại core cạnh tranh dưới luật net ngay).
    if fam:
        hist = mem.family_history(fam, limit=1)
        if hist and (hist[0].get("n_trades") or 0) == 0:
            return True
        if hist and hist[0].get("expectancy") is not None \
           and hist[0]["expectancy"] <= 0:
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
    agent, universe, context_summary, cfg, extra_agents: list | None = None,
    tier: str = "short",
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
        code, params, err = generate_strategy(ag, context_summary=context_summary,
                                              horizon_days=cfg.horizon_days)
        # `err and not code` (bản cũ) KHÔNG chặn được ca hay gặp nhất: LLM trả
        # code HỎNG (SyntaxError / import / AST reject) — `code` vẫn non-empty
        # nên lọt qua, được backtest (mọi cửa sổ raise → 0 trade) rồi LƯU luôn
        # vào SQLite. Máy user 06/08: 8/29 chiến lược trong kho là rác kiểu này.
        # Có err = không dùng được, chấm hết.
        if err:
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
    metrics = apply_selection_penalty(metrics, len(candidates))

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
        tier=tier,
        family_id=family,
    )
    mem.save_backtest(sid, ps, pe, ",".join(universe[:10]), metrics)
    if metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
       and (metrics.get("expectancy") or -999) > 0 \
       and _validation_ok(metrics):
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
    try:
        _cur_params = json.loads(active.get("params_json") or "{}")
    except Exception:
        _cur_params = {}
    # Benchmark cùng cost-basis (net phí) — xem comment ở _do_tune: đọc row
    # DB cũ (gross) làm chuẩn thì candidate net không bao giờ thắng.
    cur_metrics, _ps0, _pe0 = _do_backtest(code, _cur_params, cfg)
    mem.save_backtest(active["id"], _ps0, _pe0,
                      ",".join(cfg.universe[:10]), cur_metrics)

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
        if err:            # xem chú thích ở nhánh cold-start (develop_and_backtest)
            continue
        metrics, ps, pe = _do_backtest(new_code, new_params, cfg)
        candidates.append((ag.name, new_code, new_params, metrics, ps, pe))

    if not candidates:
        return None, {"error": "no valid revision from any agent"}

    # Competition: pick the candidate with highest expectancy
    best = max(candidates, key=lambda c: c[3].get("expectancy") or -999)
    best_agent, best_code, best_params, best_metrics, best_ps, best_pe = best
    best_metrics = apply_selection_penalty(best_metrics, len(candidates))
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
        tier=(active.get("tier") or "short"),
        family_id=family,
    )
    mem.save_backtest(sid, best_ps, best_pe, ",".join(cfg.universe[:10]), best_metrics)

    cur_exp = cur_metrics.get("expectancy") or -999
    new_exp = best_metrics.get("expectancy") or -999
    if new_exp > cur_exp and best_metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
       and _validation_ok(best_metrics):
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
    if not cur_params:
        return active["id"], {"error": "active strategy has no params to tune"}
    # RE-BACKTEST active làm benchmark CÙNG cost-basis thay vì đọc row DB cũ:
    # sau khi phí vào backtest (14/07), expectancy lịch sử là GROSS còn mọi
    # ứng viên là NET (−0.4/lệnh) → so net-vs-gross thì không ứng viên nào
    # qua nổi, tune đóng băng vĩnh viễn và active không bao giờ có row mới
    # (thấy thật 15/07: train xong mà latest_backtest vẫn là row cũ, không
    # có validation). Lưu row mới luôn → panel/CLI thấy 🧪 của active.
    cur_metrics, _ps0, _pe0 = _do_backtest(code, cur_params, cfg)
    mem.save_backtest(active["id"], _ps0, _pe0,
                      ",".join(cfg.universe[:10]), cur_metrics)

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
    new_metrics = apply_selection_penalty(new_metrics, len(candidates))
    cur_exp = cur_metrics.get("expectancy") or -999
    new_exp = new_metrics.get("expectancy") or -999

    # Sàn n_trades GIỐNG cổng cold-start/revise — tune là đường DUY NHẤT từng
    # thiếu nó (lộ 13/08: tune thắng bằng cách co 67 lệnh còn 19 — co mẫu là
    # cách rẻ nhất để thổi expectancy khi thi đấu theo expectancy).
    if new_exp > cur_exp \
       and new_metrics.get("n_trades", 0) >= MIN_TRADES_TO_VALIDATE \
       and _validation_ok(new_metrics):
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
    tier: str = "short",
) -> tuple[Optional[int], dict]:
    """Develop / tune / revise the active strategy OF ONE TIER. Adaptive cadence.

    Modes:
      auto    — choose tune vs revise based on age + stability flag (default)
      tune    — force daily tune (params only); cold-start if no active
      revise  — force weekly revise (rewrite core)
      fresh   — force cold start (ignore existing active, retire it)

    All enabled agents share one family PER TIER. `agent` is the lead;
    `extra_agents` additional agents in the daily tune competition. `tier`
    ("short" 5 phiên / "position" 20 phiên) chọn active + config riêng —
    hai tier chạy song song, không tranh ghế (xem TIER_CONFIGS).
    """
    if cfg is None:
        cfg = tier_config(tier, universe)
    cfg.universe = universe  # ensure consistency

    active = mem.get_active_family(tier=tier)

    if mode == "fresh" or active is None:
        return _cold_start(agent, universe, context_summary, cfg,
                           extra_agents=extra_agents, tier=tier)

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
        # Horizon theo TIER của chính chiến lược sinh rec — rec của tầng vị
        # thế phải sống 20 phiên, không phải 5 (reconcile đóng theo số này).
        _tier_h = TIER_CONFIGS.get(s.get("tier") or "short", {}).get("horizon_days")
        _rec_horizon = int(_tier_h or horizon_days)
        # Strategy params live in params_json (e.g. rsi_period, ma_window).
        # Without these, code that reads params['rsi_period'] throws KeyError
        # on every ticker — same pattern used by backtest()/analyze_ticker().
        try:
            params = json.loads(s.get("params_json") or "{}")
        except Exception:
            params = {}
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
                raw = EXECUTOR.run(code, window, params)
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
            entry  = _round_to_tick(sig["entry"], ticker)
            tp, sl, _ = _sanitize_targets(
                sig["action"], entry, sig["tp"], sig["sl"], ticker
            )
            stats["n_buy"] += 1
            # Close any prior open rec for this ticker — the new scan
            # supersedes it. Avoids duplicate rows piling up across scans.
            try:
                mem.supersede_open_recommendations(ticker)
            except Exception:
                pass
            rec_id = mem.save_recommendation(
                ticker=ticker,
                action=sig["action"],
                entry=entry,
                tp=tp,
                sl=sl,
                rationale=f"Strategy #{s['id']} ({s['name']}), conf={sig['confidence']:.2f}",
                horizon_days=_rec_horizon,
                brief_id=brief_id,
                strategy_id=s["id"],
            )
            recs.append({
                "id":       rec_id,
                "ticker":   ticker,
                "entry":    entry,
                "tp":       tp,
                "sl":       sl,
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

QUY TẮC: chỉ phân tích từ 5 chỉ số kỹ thuật bên dưới. KHÔNG được tham khảo
trí nhớ về giá cũ, mức Fibonacci, news, hay bất kỳ số liệu ngoài. Lý do
phải bám vào RSI/MA/volume/xu hướng — nếu không đủ data, ghi 'không đủ
dữ liệu để có ý kiến chắc chắn'.

Ticker: {ticker}
Chỉ số kỹ thuật:
  Giá đóng cửa : {close:,.0f} VND
  RSI(14)      : {rsi:.1f}  ({rsi_desc})
  MA20         : {ma20:,.0f} ({vs_ma20_desc} {vs_ma20_pct:+.1f}%)
  Volume/TB20  : {vol_ratio:.1f}x
  Xu hướng 5N  : {trend_5d:+.1f}%

Chiến lược AI đang gợi ý: {action_upper}
  Entry: {entry_str}  |  TP: {tp_str}  |  SL: {sl_str}

Dựa trên phân tích kỹ thuật CỦA BẠN (chỉ từ 5 chỉ số trên), trả lời CHÍNH XÁC
theo format sau (không thêm text khác, không nhắc giá khác ngoài data):
ĐÁNH GIÁ: MUA|BÁN|KHÔNG GIAO DỊCH
ĐỒNG Ý VỚI STRATEGY: CÓ|KHÔNG
LÝ DO: [1-2 câu, BẮT BUỘC trích chỉ số cụ thể từ data trên]
"""

_TICKER_ANALYSIS_PROMPT = """\
Bạn là chuyên gia phân tích kỹ thuật cổ phiếu Việt Nam.

QUY TẮC KHÔNG ĐƯỢC VI PHẠM:
- Mọi mức giá (entry, TP, SL, hỗ trợ, kháng cự) PHẢI lấy từ "DỮ LIỆU KỸ THUẬT"
  hoặc "TÍN HIỆU TỪ AI STRATEGY" bên dưới. KHÔNG được tham khảo trí nhớ /
  training data / Fibonacci tự tính / mức giá lịch sử bạn từng thấy.
- Nếu data không cung cấp một mức cần thiết → viết "Chưa có dữ liệu mức X",
  KHÔNG suy đoán.
- Tin tức: chỉ dùng tin có trong phần "TIN TỨC GẦN ĐÂY". Nếu phần đó ghi
  "Không có tin tức" → KHÔNG được tự bịa headline.

Ticker: {ticker} — Ngày phân tích: {date}

=== DỮ LIỆU KỸ THUẬT ===
Giá hiện tại : {close:>12,.0f} VND
RSI(14)      : {rsi:>10.1f}  ({rsi_desc})
MA20         : {ma20:>12,.0f} VND  | Giá đang {vs_ma20_desc} MA20 ({vs_ma20_pct:+.1f}%)
Volume/TB20  : {vol_ratio:>10.1f}x
Xu hướng 5N  : {trend_5d:>10.1f}%
52W High/Low : {high_52w:,.0f} / {low_52w:,.0f} VND
{pivots_block}
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

**Quyết định:** MUA / BÁN / KHÔNG GIAO DỊCH — nêu mức giá cụ thể (chỉ từ data trên).

**Giá vào lệnh:** Giá cụ thể (lấy từ Entry gợi ý hoặc MA20 trong data) + lý do.

**Giá chốt lời (Take Profit):** Giá cụ thể (lấy từ TP của strategy hoặc Pivots R1/R2 nếu data có) + lý do.

**Giá cắt lỗ (Cut Loss):** Giá cụ thể (lấy từ SL của strategy hoặc Pivots S1 nếu data có) + lý do.

**Lý do kỹ thuật:** 2-3 câu phân tích dựa trên RSI, MA, volume, xu hướng từ data trên.

**Tin tức ảnh hưởng:** CHỈ nhắc tin có trong "TIN TỨC GẦN ĐÂY". Nếu phần đó trống/không có → ghi "Không có tin tức mới trong cache". KHÔNG bịa.

**Rủi ro cần lưu ý:** 1-2 điều kiện cụ thể khiến phải thay đổi quyết định.

Yêu cầu: dùng SỐ LIỆU CỤ THỂ từ data trên, ngắn gọn, không vòng vo, không thêm số mới.
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


def _ticker_pivots(df: pd.DataFrame, close: float) -> str:
    """Compute 60-bar swing-pivot S/R for a single ticker.

    Returns a formatted block ready to paste into the analysis prompt.
    Falls back to an explicit "no data" sentinel so the LLM cannot
    invent S/R levels when the history is too short.
    """
    try:
        if df is None or df.empty or len(df) < 30:
            return ("Pivots S/R : ⚠️ Chưa đủ dữ liệu (cần ≥30 bars) — "
                    "KHÔNG suy đoán hỗ trợ/kháng cự.\n")
        high = df["high"].astype(float)
        low  = df["low"].astype(float)
        # Last ~60 bars excluding the latest 2 (avoid self-reference)
        h_window = high.tail(62).iloc[:-2] if len(high) >= 62 else high.iloc[:-2]
        l_window = low.tail(62).iloc[:-2]  if len(low)  >= 62 else low.iloc[:-2]
        above = sorted({round(float(v), 0) for v in h_window if v > close})
        below = sorted({round(float(v), 0) for v in l_window if v < close}, reverse=True)
        r1 = above[0] if len(above) >= 1 else None
        r2 = above[1] if len(above) >= 2 else None
        s1 = below[0] if len(below) >= 1 else None
        s2 = below[1] if len(below) >= 2 else None
        parts = []
        if s2 is not None: parts.append(f"S2={s2:,.0f}")
        if s1 is not None: parts.append(f"S1={s1:,.0f}")
        if r1 is not None: parts.append(f"R1={r1:,.0f}")
        if r2 is not None: parts.append(f"R2={r2:,.0f}")
        if not parts:
            return ("Pivots S/R : ⚠️ Không có pivot rõ ràng — "
                    "KHÔNG suy đoán mức.\n")
        return ("Pivots S/R : " + " | ".join(parts)
                + "  ← DÙNG ĐÚNG mức này khi viết entry/TP/SL\n")
    except Exception:
        return ("Pivots S/R : ⚠️ Lỗi tính pivot — "
                "KHÔNG suy đoán hỗ trợ/kháng cự.\n")


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

    # Fetch per-ticker news context — explicit "no news" sentinel when
    # cache empty so the LLM can't invent headlines from training data.
    _news_section = ""
    _news_found = False
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
                    _news_found = True
            if _news_found:
                _news_section = "\n".join(_lines) + "\n"
    except Exception:
        pass
    if not _news_found:
        _news_section = (
            f"\n=== TIN TỨC GẦN ĐÂY ===\n"
            f"⚠️ KHÔNG CÓ tin tức cho {ticker} trong cache 5 ngày gần đây. "
            f"KHÔNG được nhắc bất kỳ headline nào.\n"
        )

    # Compute swing pivots from the SAME df we used for indicators, so
    # AI can cite real S/R levels instead of guessing from memory.
    _pivots_block = _ticker_pivots(df, close)

    prompt = _TICKER_ANALYSIS_PROMPT.format(
        ticker=ticker,
        date=_date_cls.today().isoformat(),
        close=close,
        rsi=rsi, rsi_desc=rsi_desc,
        ma20=indic["ma20"], vs_ma20_desc=vs_ma20_desc, vs_ma20_pct=vs_ma20_pct,
        vol_ratio=indic["vol_ratio"],
        trend_5d=indic["trend_5d"],
        high_52w=indic["high_52w"], low_52w=indic["low_52w"],
        pivots_block=_pivots_block,
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

        _pivots_block_c = _ticker_pivots(df, close)
        analysis_prompt = _TICKER_ANALYSIS_PROMPT.format(
            ticker=ticker,
            date=_date_cls.today().isoformat(),
            close=close,
            rsi=rsi, rsi_desc=rsi_desc,
            ma20=indic["ma20"], vs_ma20_desc=vs_ma20_desc, vs_ma20_pct=vs_ma20_pct,
            vol_ratio=indic["vol_ratio"], trend_5d=indic["trend_5d"],
            high_52w=indic["high_52w"], low_52w=indic["low_52w"],
            pivots_block=_pivots_block_c,
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


# ── Tự kiểm chiến lược ĐÃ LƯU với sandbox hiện tại ─────────────────────────

def audit_saved_strategies(limit: int = 50) -> dict:
    """Chạy `_validate_ast` lên mọi chiến lược trong SQLite → báo cáo cái nào
    sẽ bị sandbox từ chối.

    Sinh ra sau đợt siết sandbox 06/08: danh sách trắng attribute có thể
    thiếu một API hợp lệ mà chiến lược ĐANG CHẠY của user dùng — backtest bắt
    mọi exception theo từng cửa sổ nên nó sẽ chết ÂM THẦM (0 trade → bị coi
    là chiến lược tồi → retire). Lệnh này để phát hiện TRƯỚC khi chạy đêm:

        python vnstock_strategy.py --audit-saved

    Attribute nào bị từ chối oan → thêm vào `_ALLOWED_ATTRS` (hoặc tạm bật
    VNSTOCK_STRATEGY_STRICT_ATTRS=0 rồi báo để bổ sung).
    """
    out = {"checked": 0, "ok": 0, "rejected": [], "active_ok": None}
    try:
        with mem._conn() as c:
            rows = c.execute(
                "SELECT id, name, status, code FROM strategies "
                "ORDER BY created_at DESC LIMIT ?", (limit,),
            ).fetchall()
    except Exception as e:
        if "no such table" in str(e).lower():
            return out            # máy chưa train lần nào — không phải lỗi
        out["error"] = f"không đọc được SQLite: {type(e).__name__}: {e}"
        return out

    for row in rows:
        r = dict(row)
        out["checked"] += 1
        try:
            _validate_ast(r.get("code") or "")
            out["ok"] += 1
            if r.get("status") == "active":
                out["active_ok"] = True
        except StrategyValidationError as e:
            out["rejected"].append({
                "id": r.get("id"), "name": r.get("name"),
                "status": r.get("status"), "reason": str(e)[:200],
            })
            if r.get("status") == "active":
                out["active_ok"] = False
    return out


if __name__ == "__main__":
    import argparse as _ap

    _p = _ap.ArgumentParser(description="Strategy sandbox utilities")
    _p.add_argument("--audit-saved", action="store_true",
                    help="Kiểm chiến lược đã lưu trong SQLite với sandbox hiện tại")
    _p.add_argument("--limit", type=int, default=50)
    _a = _p.parse_args()

    if _a.audit_saved:
        rep = audit_saved_strategies(limit=_a.limit)
        if rep.get("error"):
            print(f"✗ {rep['error']}")
            raise SystemExit(2)
        print(f"Đã kiểm {rep['checked']} chiến lược · {rep['ok']} qua sandbox")
        for r in rep["rejected"]:
            print(f"  ✗ [{r['status']}] #{r['id']} {r['name']}: {r['reason']}")
        if rep["active_ok"] is False:
            print("\n⚠️  CHIẾN LƯỢC ĐANG ACTIVE bị sandbox từ chối — backtest đêm "
                  "sẽ ra 0 trade.\n   Thuốc: thêm attribute vào _ALLOWED_ATTRS "
                  "(vnstock_strategy.py), hoặc tạm đặt\n   "
                  "VNSTOCK_STRATEGY_STRICT_ATTRS=0 trong .env rồi báo để bổ sung.")
            raise SystemExit(1)
        if not rep["rejected"]:
            print("✓ Tất cả đều qua sandbox")
        raise SystemExit(0)
    _p.print_help()
