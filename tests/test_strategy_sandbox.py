"""Tests cho sandbox chiến lược — code do LLM sinh, chạy trên máy user.

AUDIT 06/08/2026, lỗi CRITICAL: `_validate_ast` chỉ chặn import / tên cấm /
attribute DUNDER, trong khi `_safe_globals` phơi NGUYÊN module pandas. Chuỗi
`pd.io.common.os.system('...')` toàn tên THƯỜNG, không import, không dunder
→ lọt cổng kiểm và chạy lệnh shell thật trên máy (đã tái hiện được). Ngoài
ra `_FORBIDDEN_MODULES` là code chết (khai báo nhưng không nơi nào dùng).

Trước đợt này sandbox KHÔNG có một test nào — đó là lý do lỗ hổng sống sót
lâu. File này khoá lại: mỗi kỹ thuật thoát = 1 test, cộng test đối chứng
rằng chiến lược HỢP LỆ vẫn chạy bình thường (danh sách trắng không được
siết tới mức phá code thật).

Hermetic: không mạng, không ghi ngoài tmp_path.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import vnstock_strategy as vs


def _ohlcv(n: int = 80) -> pd.DataFrame:
    """Khung giá đủ dài cho chiến lược mẫu (cần >= 50 bar)."""
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 1.2, n))
    return pd.DataFrame({
        "time": pd.date_range("2026-01-02", periods=n, freq="B"),
        "open": close + rng.normal(0, 0.3, n),
        "high": close + np.abs(rng.normal(1.0, 0.4, n)),
        "low": close - np.abs(rng.normal(1.0, 0.4, n)),
        "close": close,
        "volume": rng.integers(500_000, 2_000_000, n).astype(float),
    })


def _wrap(body: str) -> str:
    """Bọc payload vào đúng contract signal(df, params)."""
    return (
        "def signal(df, params):\n"
        f"    {body}\n"
        "    return {'action': 'hold', 'entry': 0, 'tp': 0, 'sl': 0, "
        "'confidence': 0}\n"
    )


# ── Đường thoát ĐÃ XÁC NHẬN khai thác được (audit 06/08) ───────────────────

def test_module_traversal_to_os_is_rejected(tmp_path):
    """Khai thác gốc: pd → io → common → os → system. Toàn tên thường nên
    cổng kiểm cũ cho qua và lệnh shell chạy thật."""
    proof = tmp_path / "escape_proof.txt"
    code = _wrap(f"pd.io.common.os.system('touch {proof}')")

    with pytest.raises(Exception):
        vs.EXECUTOR.run(code, _ohlcv(), {})

    assert not proof.exists(), "SANDBOX ESCAPE: lệnh shell đã chạy thật"


def test_module_traversal_blocked_even_if_validator_skipped(tmp_path):
    """Phòng thủ nhiều lớp: kể cả khi cổng kiểm AST bị bỏ qua, sandbox vẫn
    phải chặn ở tầng RUNTIME — `pd.io` không được tồn tại trong scope."""
    proof = tmp_path / "escape_proof2.txt"
    code = _wrap(f"pd.io.common.os.system('touch {proof}')")
    g = vs._safe_globals(_ohlcv(), {})
    loc: dict = {}

    exec(compile(code, "<t>", "exec"), g, loc)          # KHÔNG qua _validate_ast
    with pytest.raises(Exception):
        loc["signal"](_ohlcv(), {})

    assert not proof.exists(), "SANDBOX ESCAPE ở tầng runtime"


def test_numpy_and_math_modules_are_also_sealed():
    """np/math cũng phải là "khay" chỉ chứa hàm đã duyệt, không phải module."""
    g = vs._safe_globals(_ohlcv(), {})
    for mod_name in ("np", "math"):
        with pytest.raises(Exception):
            getattr(g[mod_name], "os")
    # hàm hợp lệ vẫn lấy được
    assert g["np"].mean([1, 2, 3]) == 2
    assert g["math"].sqrt(9) == 3


# ── Ghi file / thực thi chuỗi qua chính đối tượng DataFrame ────────────────

def test_dataframe_file_write_methods_are_rejected(tmp_path):
    """`open` bị chặn nhưng df.to_csv/to_pickle ghi file y hệt — cổng cũ
    không đụng tới vì chúng chỉ là attribute thường."""
    for meth in ("to_csv", "to_pickle", "to_parquet", "to_json"):
        proof = tmp_path / f"{meth}.out"
        with pytest.raises(Exception):
            vs.EXECUTOR.run(_wrap(f"df.{meth}('{proof}')"), _ohlcv(), {})
        assert not proof.exists(), f"SANDBOX ESCAPE: df.{meth} ghi được file"


def test_dataframe_string_eval_methods_are_rejected():
    """df.query/df.eval thực thi CHUỖI (engine python) — cửa hậu cho eval."""
    for body in ("df.query('close > 0')", "df.eval('close * 2')"):
        with pytest.raises(Exception):
            vs.EXECUTOR.run(_wrap(body), _ohlcv(), {})


# ── Đi ngược cây lớp mà KHÔNG dùng dunder ─────────────────────────────────

def test_mro_walk_is_rejected():
    """type(df).mro() chạm tới `object` bằng method THƯỜNG — bộ lọc dunder
    cũ không thấy gì."""
    with pytest.raises(Exception):
        vs.EXECUTOR.run(_wrap("x = type(df).mro()"), _ohlcv(), {})


def test_format_protocol_dunder_leak_is_rejected():
    """"{0.__class__}".format(df) chạm dunder QUA CHUỖI — AST không soi được
    nội dung string literal nên bộ lọc dunder vô hiệu."""
    with pytest.raises(Exception):
        vs.EXECUTOR.run(_wrap("x = '{0.__class__}'.format(df)"), _ohlcv(), {})


def test_bare_forbidden_module_name_is_rejected():
    """_FORBIDDEN_MODULES trước đây là CODE CHẾT (khai báo mà không dùng)."""
    for mod in ("os", "sys", "subprocess", "socket"):
        with pytest.raises(vs.StrategyValidationError):
            vs._validate_ast(_wrap(f"x = {mod}"))


# ── Các chốt cũ phải còn nguyên (chống regress) ───────────────────────────

def test_classic_escapes_still_blocked():
    for body in (
        "x = df.__class__",
        "x = open('/etc/passwd')",
        "x = eval('1+1')",
        "x = exec('pass')",
        "x = getattr(df, 'to_csv')",
        "x = globals()",
    ):
        with pytest.raises(vs.StrategyValidationError):
            vs._validate_ast(_wrap(body))


def test_import_forms_still_blocked():
    for code in ("import os\ndef signal(df, params): return {}",
                 "from os import system\ndef signal(df, params): return {}"):
        with pytest.raises(vs.StrategyValidationError):
            vs._validate_ast(code)


# ── ĐỐI CHỨNG: chiến lược hợp lệ KHÔNG được vạ lây ────────────────────────

_REAL_STRATEGY = """
def signal(df, params):
    if len(df) < 50:
        return {"action": "hold", "entry": 0, "tp": 0, "sl": 0, "confidence": 0}
    close = df['close'].astype(float)
    high  = df['high'].astype(float)
    low   = df['low'].astype(float)
    vol   = df['volume'].astype(float)

    ma_short = close.rolling(params['ma_short']).mean()
    ma_long  = close.rolling(params['ma_long']).mean()
    delta = close.diff()
    up = delta.clip(lower=0).ewm(com=13).mean()
    dn = (-delta).clip(lower=0).ewm(com=13).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    tr = pd.concat([(high - low), (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(params['atr_period']).mean()
    avg_vol = vol.rolling(20).mean()

    last = -1
    c = float(close.iloc[last])
    a = float(atr.iloc[last]) if not pd.isna(atr.iloc[last]) else c * 0.02
    slope = (ma_long.iloc[last] - ma_long.iloc[last - 5]) / max(ma_long.iloc[last - 5], 1e-9)
    if params.get('regime_filter', True) and slope < params['min_slope']:
        return {"action": "hold", "entry": c, "tp": 0, "sl": 0, "confidence": 0.0}

    conf_trend = c > ma_short.iloc[last] and ma_short.iloc[last] > ma_long.iloc[last]
    conf_mom = (rsi.iloc[last - 1] < params['rsi_oversold_exit']
                and rsi.iloc[last] > rsi.iloc[last - 1])
    conf_vol = vol.iloc[last] > params['vol_mult'] * avg_vol.iloc[last]
    confluence = sum([conf_trend, conf_mom, conf_vol])

    if confluence >= 2:
        entry = c
        return {"action": "buy", "entry": entry,
                "tp": entry + params['tp_atr_mult'] * a,
                "sl": entry - params['sl_atr_mult'] * a,
                "confidence": min(0.95, 0.4 + 0.15 * confluence)}
    return {"action": "hold", "entry": c, "tp": 0, "sl": 0, "confidence": 0.0}
"""

_REAL_PARAMS = {"ma_short": 10, "ma_long": 20, "rsi_oversold_exit": 40,
                "vol_mult": 1.2, "atr_period": 14, "sl_atr_mult": 2.0,
                "tp_atr_mult": 3.0, "min_slope": -0.005, "regime_filter": True}


def test_canonical_strategy_from_prompt_still_runs():
    """Chiến lược MẪU trong _STRATEGY_PROMPT (thứ LLM được dạy để viết) phải
    chạy trót lọt — danh sách trắng siết quá tay là giết chiến lược thật."""
    out = vs.EXECUTOR.run(_REAL_STRATEGY, _ohlcv(), _REAL_PARAMS)
    assert out["action"] in ("buy", "sell", "hold")
    assert isinstance(out["confidence"], (int, float))


def test_common_quant_idioms_still_allowed():
    """Các API quant hay dùng nhưng không có trong chiến lược mẫu."""
    body = (
        "s = df['close']\n"
        "    x = s.pct_change().dropna().std()\n"
        "    y = np.where(s > s.mean(), 1, 0).sum()\n"
        "    z = s.ewm(span=12).mean().iloc[-1] - s.rolling(26).mean().iloc[-1]\n"
        "    w = float(np.nanmax(s.values)) + math.log(2)\n"
        "    q = s.quantile(0.75) - s.expanding().min().iloc[-1]\n"
        "    r = s.tail(10).reset_index(drop=True).sort_values().tolist()[0]\n"
        "    v = abs(round(s.diff().fillna(0).cumsum().iloc[-1], 2))"
    )
    vs.EXECUTOR.run(_wrap(body), _ohlcv(), {})          # không được raise


def test_strict_executor_shares_the_same_gate(tmp_path):
    """STRICT_EXECUTOR spawn subprocess nhưng _signal_worker dựng CÙNG
    _safe_globals — nó phải chặn y hệt, không được lỏng hơn."""
    proof = tmp_path / "escape_strict.txt"
    with pytest.raises(Exception):
        vs.STRICT_EXECUTOR.run(
            _wrap(f"pd.io.common.os.system('touch {proof}')"), _ohlcv(), {})
    assert not proof.exists()


# ── Tự kiểm chiến lược đã lưu (chống chết âm thầm sau khi siết) ────────────

def test_audit_saved_strategies_flags_active_rejection(monkeypatch):
    """Siết sandbox có thể làm chiến lược ĐANG ACTIVE của user bị từ chối →
    backtest nuốt exception theo cửa sổ nên chết ÂM THẦM (0 trade → bị coi
    là chiến lược tồi → retire). Lệnh audit phải chỉ đúng mặt."""
    rows = [
        {"id": 1, "name": "ok-strat", "status": "retired",
         "code": "def signal(df, params):\n    return {'action': 'hold'}\n"},
        {"id": 2, "name": "bad-strat", "status": "active",
         "code": "def signal(df, params):\n    df.to_csv('/tmp/x')\n"},
    ]

    class _FakeCursor:
        def fetchall(self):
            return rows

    class _FakeConn:
        def execute(self, *a, **kw):
            return _FakeCursor()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(vs.mem, "_conn", lambda: _FakeConn())

    rep = vs.audit_saved_strategies()

    assert rep["checked"] == 2 and rep["ok"] == 1
    assert rep["active_ok"] is False
    assert rep["rejected"][0]["id"] == 2 and "to_csv" in rep["rejected"][0]["reason"]


def test_audit_saved_strategies_fresh_machine_is_not_an_error(monkeypatch):
    """Máy chưa train lần nào (chưa có bảng strategies) không phải lỗi."""
    class _Boom:
        def execute(self, *a, **kw):
            raise Exception("no such table: strategies")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(vs.mem, "_conn", lambda: _Boom())

    rep = vs.audit_saved_strategies()
    assert "error" not in rep and rep["checked"] == 0
