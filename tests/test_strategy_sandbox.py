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


# ── VÒNG 2 (red-team 06/08): string-dispatch của pandas ────────────────────
# Đội đối kháng phá được bản vá vòng 1: `.apply`/`.agg`/`.aggregate`/
# `.transform` nhận TÊN METHOD DẠNG CHUỖI rồi tự getattr(obj, name)() lúc
# chạy. Tên nằm trong string literal (ast.Constant) nên mọi kiểm tra trên
# ast.Attribute — kể cả _FORBIDDEN_ATTRS có sẵn 'to_csv' — đều không thấy.
# Hậu quả đã chứng minh: ghi file tuỳ ý (path + nội dung do attacker chọn),
# kể cả .pth vào site-packages = code chạy mỗi lần khởi động Python.

@pytest.mark.parametrize("body", [
    "df['close'].apply('to_csv', args=('{p}',))",
    "df.agg('to_csv', 0, '{p}')",
    "df.aggregate('to_csv', 0, '{p}')",
    "df.transform('to_csv', 0, '{p}')",
    "df.agg('to_pickle', 0, '{p}')",
    "df['close'].apply('to_json', args=('{p}',))",
    "df.agg(func='to_csv', path_or_buf='{p}')",
])
def test_string_dispatch_file_write_is_rejected(tmp_path, body):
    proof = tmp_path / "pwned.out"
    code = _wrap(body.format(p=proof))

    with pytest.raises(Exception):
        vs.EXECUTOR.run(code, _ohlcv(), {})

    assert not proof.exists(), f"SANDBOX ESCAPE qua string-dispatch: {body}"


def test_string_dispatch_blocked_at_ast_layer():
    """Phải chặn ngay ở AST — chặn muộn hơn là file đã ghi xong rồi (agg
    ném lỗi SAU khi to_csv chạy, nên 'có exception' KHÔNG có nghĩa là an toàn)."""
    with pytest.raises(vs.StrategyValidationError):
        vs._validate_ast(_wrap("df.agg('to_csv', 0, '/tmp/x')"))


def test_computed_method_name_also_rejected():
    """Chuỗi ghép động ('to_' + 'csv') hay biến chuỗi cũng không được lọt —
    lý do luật là 'đối số đầu PHẢI là lambda viết thẳng', không phải 'cấm
    chuỗi trông giống tên nguy hiểm'."""
    for body in ("df.agg('to_' + 'csv', 0, '/tmp/x')",
                 "f = 'to_csv'\n    df.agg(f, 0, '/tmp/x')",
                 "df.apply(['to_csv'])"):
        with pytest.raises(vs.StrategyValidationError):
            vs._validate_ast(_wrap(body))


def test_lambda_apply_still_allowed():
    """ĐỐI CHỨNG: rolling(...).apply(lambda) là idiom quant hợp lệ — luật mới
    chỉ cấm dạng CHUỖI, không cấm cả họ .apply."""
    body = ("x = df['close'].rolling(5).apply(lambda w: w.max() - w.min(), "
            "raw=False).iloc[-1]")
    vs.EXECUTOR.run(_wrap(body), _ohlcv(), {})


# ── VÒNG 2: false positive — danh sách trắng siết oan chiến lược thật ──────

@pytest.mark.parametrize("body", [
    "x = df.close.iloc[-1]",                       # truy cập cột kiểu attribute
    "x = df['close'].subtract(df['open']).mean()",
    "x = df['high'].multiply(2).divide(3).iloc[-1]",
    "x = df['close'].to_frame().shape[0]",
    "x = df['close'].values.argsort()[-1]",
    "x = float(np.average(df['close'], weights=df['volume']))",
    "x = float(np.gradient(df['close'].values)[-1])",
    "x = float(np.ptp(df['close'].values))",
    "x = float(np.degrees(np.arctan(0.5)))",
    "x = int(np.count_nonzero(df['close'] > 0))",
    "x = bool(np.isclose(1.0, 1.0))",
    "x = float(np.nanpercentile(df['close'].values, 75))",
    "x = df['close'].kurtosis()",
    "x = df['close'].last_valid_index()",
    "x = df[['close']].corrwith(df['open'])",
    "x = df['close'].searchsorted(100)",
    "x = df['close'].equals(df['close'])",
    "x = df.filter(['close']).shape[1]",
    "try:\n        x = 1 / 0\n    except ZeroDivisionError:\n        x = 0",
    "x = pow(2, 3)",
])
def test_legit_quant_idioms_not_falsely_rejected(body):
    """Red-team viết 12 chiến lược thật → 6 chết vì danh sách trắng vòng 1
    thiếu tên. Mỗi dòng dưới đây là một idiom hợp lệ từng bị chặn oan."""
    vs.EXECUTOR.run(_wrap(body), _ohlcv(), {})


def test_ast_allowlist_and_runtime_trays_are_consistent():
    """Bất nhất vòng 1 (red-team phát hiện): `power/greater/less/equal` nằm
    trong khay np nhưng bị AST chặn trước khi tới; ngược lại `unique/degrees/
    append/hypot` qua AST nhưng khay thiếu → chết ở runtime. Mọi tên trong
    khay PHẢI có trong danh sách trắng AST."""
    trays = vs._PD_SAFE | vs._NP_SAFE | vs._MATH_SAFE
    missing = {n for n in trays if n not in vs._ALLOWED_ATTRS}
    assert not missing, f"tên trong khay nhưng AST chặn: {sorted(missing)}"


@pytest.mark.parametrize("body", [
    "df.agg(params['m'], 0, '{p}')",                  # tên qua params (LLM tune)
    "df.agg('to_' + 'csv', 0, '{p}')",                # chuỗi ghép động
    "m = 'to_csv'\n    df.agg(m, 0, '{p}')",          # biến chuỗi
    "df.agg(f'to_csv', 0, '{p}')",                    # f-string
    "df.agg(['to_csv'], 0, '{p}')",                   # list chuỗi
    "df['close'].apply(lambda s: df.agg('to_csv', 0, '{p}'))",   # lồng trong lambda
    "df.groupby('close').agg('to_csv', 0, '{p}')",
    "df['close'].rolling(3).agg('to_csv', '{p}')",
    "df.set_index('time').resample('D').agg('to_csv', 0, '{p}')",
    "df['close'].ewm(span=3).agg('to_csv', '{p}')",
    "df['close'].expanding().agg('to_csv', '{p}')",
])
def test_dispatch_bypass_variants_all_blocked(tmp_path, body):
    """Luật áp theo TÊN METHOD nên phủ mọi đối tượng trung gian (groupby/
    rolling/resample/ewm/expanding), và mọi cách dựng chuỗi — kể cả tên
    truyền qua `params` (params do LLM tune, cũng là input không tin được)."""
    proof = tmp_path / "v.out"
    code = _wrap(body.format(p=proof))

    with pytest.raises(Exception):
        vs.EXECUTOR.run(code, _ohlcv(), {"m": "to_csv"})

    assert not proof.exists(), f"SANDBOX ESCAPE: {body}"


# ── VÒNG 3 (red-team 06/08): bound method là OBJECT HẠNG NHẤT ─────────────
# Luật vòng 2 kiểm TẠI CHỖ GỌI (`node.func` phải là ast.Attribute) nên chỉ
# cần tách lời gọi khỏi hình dạng đó là thoát sạch: `w = df.agg` rồi
# `w('to_csv', 0, path)` có node.func là ast.Name. Red-team ghi lại được file
# tuỳ ý + .pth vào site-packages. Vòng 3 đổi luật sang THAM CHIẾU: tên
# dispatch chỉ được xuất hiện đúng ở vị trí callee của lời gọi đã qua kiểm.

@pytest.mark.parametrize("body", [
    "w = df.agg\n    w('to_csv', 0, '{p}')",
    "w = df.agg\n    try:\n        w('to_csv', 0, '{p}')\n    except Exception:\n        pass",
    "[df.agg][0]('to_csv', 0, '{p}')",
    "(lambda f: f('to_csv', 0, '{p}'))(df.agg)",
    "t = (df.agg,)\n    t[0]('to_csv', 0, '{p}')",
    "m = {{'f': df.apply}}\n    m['f']('to_csv', args=('{p}',))",
    "g = lambda x, f=df.agg: f('to_csv', 0, '{p}')\n    g(1)",
    "h = (lambda: df.agg)()\n    h('to_csv', 0, '{p}')",
    "bad = pd.DataFrame({{'c': ['x']}})\n    w = bad.agg\n    try:\n        w('to_csv', 0, '{p}', index=False, header=False)\n    except Exception:\n        pass",
    "sorted([1], key=df.agg)",
])
def test_bound_method_indirection_is_rejected(tmp_path, body):
    """Mọi cách 'cầm' method dispatch ra khỏi chỗ gọi trực tiếp đều bị từ
    chối — gán biến, list, tuple, dict, đối số lambda, default arg, giá trị
    trả về, key= của sorted."""
    proof = tmp_path / "ind.out"
    code = _wrap(body.format(p=proof))

    with pytest.raises(vs.StrategyValidationError):
        vs.EXECUTOR.run(code, _ohlcv(), {})

    assert not proof.exists(), f"SANDBOX ESCAPE qua gián tiếp: {body}"


def test_dispatch_still_callable_directly_with_lambda():
    """ĐỐI CHỨNG vòng 3: luật tham chiếu KHÔNG được giết idiom hợp lệ."""
    vs.EXECUTOR.run(_wrap(
        "x = df['close'].rolling(5).apply(lambda w: w.max() - w.min(), "
        "raw=False).iloc[-1]"), _ohlcv(), {})
    vs.EXECUTOR.run(_wrap(
        "x = df['close'].agg(lambda s: s.mean())"), _ohlcv(), {})


# ── Code HỎNG không được lọt vào SQLite (lộ từ --audit-saved máy user) ────

def test_invalid_generated_code_is_not_saved(monkeypatch):
    """Máy user 06/08: 8/29 chiến lược trong kho là rác (SyntaxError / có
    import). Nguyên nhân: guard `if err and not code: continue` — LLM trả code
    HỎNG thì `code` vẫn non-empty nên lọt qua, được backtest (mọi cửa sổ raise
    → 0 trade) rồi LƯU vào DB. Nay có err là bỏ, không cần biết code rỗng hay
    không."""
    import vnstock_strategy as _vs
    saved: list = []

    class _Ag:
        name = "fake"
        is_available = True

        def generate(self, prompt, max_tokens=2000):
            # LLM trả code hỏng — đúng thứ đã sinh ra 8 dòng rác kia
            return "PARAMS:\n{}\nCODE:\nimport os\ndef signal(df, p): pass", None

    monkeypatch.setattr(_vs.mem, "get_active_family", lambda: None)
    monkeypatch.setattr(_vs.mem, "save_strategy",
                        lambda **kw: saved.append(kw) or 1)
    monkeypatch.setattr(_vs, "_do_backtest",
                        lambda *a, **kw: ({"expectancy": 1.0, "n_trades": 50},
                                          "2026-01-01", "2026-06-01"))

    sid, out = _vs.develop_and_backtest(_Ag(), universe=["AAA"], n_iterations=0)

    assert saved == [], "code hỏng vẫn bị lưu vào SQLite"
    assert sid is None and "error" in out


def test_valid_generated_code_still_saved(monkeypatch):
    """ĐỐI CHỨNG: code hợp lệ vẫn đi trọn đường lưu."""
    import vnstock_strategy as _vs
    saved: list = []
    good = ("PARAMS:\n{\"n\": 5}\nCODE:\n"
            "def signal(df, params):\n"
            "    return {'action': 'hold', 'entry': 0, 'tp': 0, 'sl': 0, "
            "'confidence': 0}\n")

    class _Ag:
        name = "fake"
        is_available = True

        def generate(self, prompt, max_tokens=2000):
            return good, None

    monkeypatch.setattr(_vs.mem, "get_active_family", lambda: None)
    monkeypatch.setattr(_vs.mem, "save_strategy",
                        lambda **kw: saved.append(kw) or 7)
    monkeypatch.setattr(_vs.mem, "save_backtest", lambda *a, **kw: None)
    monkeypatch.setattr(_vs.mem, "promote_strategy", lambda *a, **kw: None)
    monkeypatch.setattr(_vs.mem, "set_status", lambda *a, **kw: None,
                        raising=False)
    monkeypatch.setattr(_vs, "_do_backtest",
                        lambda *a, **kw: ({"expectancy": 1.0, "n_trades": 50},
                                          "2026-01-01", "2026-06-01"))

    sid, out = _vs.develop_and_backtest(_Ag(), universe=["AAA"], n_iterations=0)

    assert len(saved) == 1 and sid == 7
