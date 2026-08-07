"""Tests cho tầng CÁCH LY NĂNG LỰC (vnstock_sandbox_runtime + IsolatedExecutor).

Vì sao có tầng này: 3 vòng red-team 06/08 chứng minh lọc cú pháp (AST) trên
một đối tượng pandas THẬT là đuổi bắt vô tận — bịt `pd.io.common.os.system`
thì lộ `df.agg('to_csv', …)`, bịt tiếp thì lộ `w = df.agg; w(…)`. Tầng mới
đổi câu hỏi: thay vì "câu lệnh này có nguy hiểm không?", khoá thẳng NĂNG LỰC
của tiến trình (không mở được file/shell/socket).

Điểm mấu chốt của file test này: mọi phép thử đều chạy **KHÔNG qua
_validate_ast** — gọi thẳng Python trong tiến trình đã `lockdown()`. Đó mới
là phép thử thật: nó trả lời "nếu ngày mai ai đó tìm được cách lách AST
(lần thứ 4), thì hệ thống còn đứng được không?".
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import vnstock_sandbox_runtime as rt

_REPO = Path(__file__).resolve().parent.parent


def _run_locked(snippet: str, extra_env: "dict | None" = None) -> str:
    """Chạy `snippet` trong tiến trình con ĐÃ lockdown, trả stdout.

    Cố ý KHÔNG đi qua _validate_ast: đây là phép thử tầng năng lực đứng một
    mình.
    """
    prog = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(_REPO)!r})
        import pandas as pd, numpy as np
        import vnstock_sandbox_runtime as rt
        rt.lockdown()
        {textwrap.indent(textwrap.dedent(snippet), ' ' * 8).strip()}
    """)
    env = dict(os.environ)
    env.update(extra_env or {})
    env["PYTHONPATH"] = str(_REPO)
    out = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                         text=True, timeout=180, env=env, cwd=str(_REPO))
    return out.stdout.strip() + ("\n[STDERR] " + out.stderr.strip()
                                 if out.stderr.strip() else "")


# ── Tầng năng lực chặn mọi đường ghi/chạy, KHÔNG cần biết cú pháp ─────────

@pytest.mark.parametrize("label,expr", [
    ("open",            "open(P, 'w')"),
    ("to_csv",          "pd.DataFrame({'a':[1]}).to_csv(P)"),
    ("to_pickle",       "pd.DataFrame({'a':[1]}).to_pickle(P)"),
    ("to_json",         "pd.DataFrame({'a':[1]}).to_json(P)"),
    ("agg-dispatch",    "pd.DataFrame({'a':[1]}).agg('to_csv', 0, P)"),
    ("alias-dispatch",  "(lambda w: w('to_csv', 0, P))(pd.DataFrame({'a':[1]}).agg)"),
    ("np.save",         "np.save(P, np.array([1,2]))"),
    ("os.system",       "pd.io.common.os.system('touch ' + P)"),
    ("subprocess",      "__import__('subprocess').run(['touch', P])"),
    ("pathlib",         "__import__('pathlib').Path(P).write_text('x')"),
    ("shutil",          "__import__('shutil').copyfile(__file__ if 0 else P, P)"),
    ("socket",          "__import__('socket').socket()"),
])
def test_capability_lockdown_blocks_escape(tmp_path, label, expr):
    """Mỗi dòng dưới đây là một đường thoát ĐÃ hoặc CÓ THỂ dùng để ra ngoài.
    Không dòng nào đi qua AST — chúng chạy thẳng bằng Python."""
    target = tmp_path / f"{label}.out"
    out = _run_locked(f"""
        P = {str(target)!r}
        try:
            {expr}
            print("LOT")
        except Exception as e:
            print("CHAN:" + type(e).__name__)
    """)

    assert out.startswith("CHAN:"), f"{label}: không chặn được — {out}"
    assert not target.exists(), f"{label}: SANDBOX ESCAPE, file đã được tạo"


def test_lockdown_keeps_pandas_and_imports_working():
    """Khoá năng lực KHÔNG được làm hỏng tính toán — đây là ranh giới mong
    manh: bản đầu khoá cả `_io.open` (hàm cơ chế import của CPython dùng) làm
    chết luôn `import` lẫn lazy-import bên trong pandas."""
    out = _run_locked("""
        import xml.etree.ElementTree as ET        # import MỚI sau khi khoá
        s = pd.Series(np.arange(200, dtype=float))
        v = s.rolling(20).mean().ewm(span=5).std().fillna(0).iloc[-1]
        g = pd.DataFrame({'a': s, 'b': s * 2}).groupby(pd.cut(s, 4),
                                                       observed=False)['b'].mean()
        print(f"OK {round(float(v), 3)} {len(g)} {ET.__name__}")
    """)

    assert out.startswith("OK "), out


def test_io_open_deliberately_not_patched():
    """Guard cho quyết định thiết kế: `_io.open` PHẢI còn nguyên. Vá nó là
    khoá luôn cơ chế import → không import được gì nữa (đã đo 06/08)."""
    assert "_io" not in rt._OPEN_NAMESPACES
    assert set(rt._OPEN_NAMESPACES) == {"builtins", "io"}


# ── Bí mật không được vào tới tiến trình worker ───────────────────────────

def test_minimal_env_carries_no_secrets(monkeypatch):
    """Worker nhận env TỐI THIỂU — key không bao giờ vào tới tiến trình chạy
    code lạ (chắc hơn dọn sau khi đã vào)."""
    monkeypatch.setenv("GEMINI_API_KEY", "sk-secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")

    env = rt.minimal_env()

    assert not [k for k in env if "KEY" in k.upper() or "TOKEN" in k.upper()]
    assert "PATH" in env and "PYTHONPATH" in env      # vẫn chạy được python


def test_scrub_runs_before_os_is_locked():
    """Lớp 2 (dọn env tại chỗ) phải chạy TRƯỚC khi khoá `os.*`: `del
    os.environ[k]` gọi xuống `os.unsetenv`, khoá trước thì mọi lần xoá đều
    ném lỗi rồi bị nuốt — hàm trả số ĐẸP mà thực tế không xoá gì (bug đã
    dính lúc đo lần đầu)."""
    out = _run_locked("""
        print("LEFT=" + ",".join(sorted(
            k for k in __import__('os').environ
            if 'API_KEY' in k.upper() or 'TOKEN' in k.upper())))
    """, extra_env={"MY_API_KEY": "x", "SOME_TOKEN": "y"})

    assert out == "LEFT=", f"bí mật còn sót trong worker: {out}"


# ── IsolatedExecutor: đầu-cuối qua tiến trình thật ────────────────────────

def _ohlcv(n: int = 80):
    import numpy as _np
    import pandas as _pd
    return _pd.DataFrame({
        "time": _pd.date_range("2026-01-02", periods=n, freq="B"),
        "open": _np.linspace(10, 12, n), "high": _np.linspace(11, 13, n),
        "low": _np.linspace(9, 11, n), "close": _np.linspace(10, 12, n),
        "volume": _np.full(n, 1e6),
    })


_GOOD = ("def signal(df, params):\n"
         "    x = float(df['close'].rolling(5).mean().iloc[-1])\n"
         "    return {'action': 'hold', 'entry': x, 'tp': 0, 'sl': 0,"
         "            'confidence': 0.5}\n")


def test_isolated_executor_runs_strategy_in_worker():
    import vnstock_strategy as vs
    ex = vs.IsolatedExecutor()
    try:
        out = ex.run(_GOOD, _ohlcv(), {})
        assert out["action"] == "hold" and out["entry"] > 0
        assert ex._proc is not None and ex._proc.poll() is None   # worker sống
        assert ex._lock_stats.get("functions", 0) > 50            # đã lockdown
    finally:
        ex.shutdown()


def test_isolated_executor_reuses_one_worker():
    """MỘT worker cho nhiều lần chạy — nếu dựng lại mỗi lần thì backtest
    (hàng nghìn cửa sổ × ~0.5s spawn trên Windows) sẽ không dùng nổi."""
    import vnstock_strategy as vs
    ex = vs.IsolatedExecutor()
    try:
        ex.run(_GOOD, _ohlcv(), {})
        pid = ex._proc.pid
        for _ in range(5):
            ex.run(_GOOD, _ohlcv(), {})
        assert ex._proc.pid == pid
    finally:
        ex.shutdown()


def test_isolated_executor_recovers_from_dead_worker():
    """Worker chết (OOM/kill) → lần gọi sau tự dựng lại, không kéo sập
    pipeline đêm."""
    import vnstock_strategy as vs
    ex = vs.IsolatedExecutor()
    try:
        ex.run(_GOOD, _ohlcv(), {})
        old = ex._proc.pid
        ex._proc.kill()
        ex._proc.wait(timeout=10)

        out = ex.run(_GOOD, _ohlcv(), {})

        assert out["action"] == "hold"
        assert ex._proc.pid != old
    finally:
        ex.shutdown()


def test_isolation_killswitch_falls_back_in_process(monkeypatch):
    import vnstock_strategy as vs
    monkeypatch.setenv("VNSTOCK_STRATEGY_ISOLATION", "0")
    ex = vs.IsolatedExecutor()
    try:
        out = ex.run(_GOOD, _ohlcv(), {})
        assert out["action"] == "hold"
        assert ex._proc is None            # không dựng worker khi đã tắt
    finally:
        ex.shutdown()


def test_default_executors_are_isolated():
    """Chốt: đường chạy MẶC ĐỊNH (backtest + emit_recommendations) phải đi
    qua tầng cách ly, không phải in-process như trước."""
    import vnstock_strategy as vs
    assert isinstance(vs.EXECUTOR, vs.IsolatedExecutor)
    assert isinstance(vs.STRICT_EXECUTOR, vs.IsolatedExecutor)

# ── FileIO: đường ĐỌC-GHI không qua `open` (tự dò ra sau khi dựng tầng này) ──

@pytest.mark.parametrize("label,expr", [
    ("io.FileIO-write",   "__import__('io').FileIO(P, 'w')"),
    ("_io.FileIO-write",  "__import__('_io').FileIO(P, 'w')"),
    ("io.FileIO-fd",      "__import__('_io').FileIO(1, 'w')"),
])
def test_fileio_write_paths_blocked(tmp_path, label, expr):
    """`io.FileIO('x','w')` ghi file mà KHÔNG đi qua `open` — bản lockdown
    đầu tiên bỏ sót, tự dò ra 06/08."""
    target = tmp_path / f"{label}.bin"
    out = _run_locked(f"""
        P = {{!r}}
        try:
            {{}}
            print("LOT")
        except Exception as e:
            print("CHAN:" + type(e).__name__)
    """.format(str(target), expr))
    assert out.startswith("CHAN:"), f"{label}: {out}"
    assert not target.exists(), f"{label}: SANDBOX ESCAPE"


def test_fileio_cannot_read_secrets():
    """Đường ĐỌC cũng phải khoá: `io.FileIO('.env','r')` là đường lộ API key
    (đọc rồi nhét vào dict trả về của signal())."""
    out = _run_locked("""
        import io
        for target in ('.env', '.env.example', '/etc/hostname'):
            try:
                data = io.FileIO(target, 'r').read(32)
                print("LOT:" + target)
                break
            except Exception:
                continue
        else:
            print("CHAN")
    """)
    assert out == "CHAN", f"đọc được file bí mật: {out}"


def test_import_machinery_survives_fileio_gate():
    """Ranh giới mong manh: `_io.FileIO`/`_io.open_code` CHÍNH LÀ thứ
    importlib dùng. Chặn cứng thì không import được gì; nên đây là CỔNG theo
    chính sách (chỉ cho đọc file module). `open_code` chỉ nhận 1 đối số —
    truyền thêm mode là TypeError giết cơ chế import (đã dính)."""
    out = _run_locked("""
        import email.mime.text, xml.dom.minidom, json, csv
        s = pd.Series(np.arange(100.0)).rolling(10).mean().iloc[-1]
        print(f"OK {round(float(s), 2)}")
    """)
    assert out.startswith("OK "), out

# ── VÒNG 4 (red-team): 5 đường phá được lớp A (setattr) → cần audit hook ──
# Bản chất chung: KHÔNG THỂ GIẤU gì khỏi code Python chạy cùng tiến trình.
# Audit hook (PEP 578) khác về CHẤT — sự kiện phát ra TỪ BÊN TRONG primitive
# ở tầng C, nên tham chiếu cũ / module import lại / class lấy qua type() đều
# đi qua nó; và sys.addaudithook KHÔNG có API gỡ.

@pytest.mark.parametrize("label,expr", [
    # 1. dựng lại module C → bản NGUYÊN GỐC chưa bị vá
    ("reimport-posix",
     "__import__('sys').modules.pop('posix', None); "
     "__import__('posix').system('touch ' + P)"),
    ("reimport-os",
     "__import__('sys').modules.pop('os', None); "
     "__import__('os').system('touch ' + P)"),
    # 2. tên exec bị bỏ sót trong deny list
    ("posix_spawn",
     "__import__('os').posix_spawn('/bin/sh', ['sh','-c','touch ' + P], {})"),
    # 3. _io.open cố ý không vá (sợ chết import)
    ("_io.open-write", "__import__('_io').open(P, 'w')"),
    # 4. module stdlib giữ THAM CHIẾU `open` gốc từ trước lockdown
    ("tokenize-builtin-open", "__import__('tokenize')._builtin_open(P, 'w')"),
    ("bz2-builtin-open", "__import__('bz2')._builtin_open(P, 'w')"),
    ("tarfile-bltn-open", "__import__('tarfile').bltn_open(P, 'w')"),
    ("numpy-datasource-open", "np.lib._datasource._open(P, 'w')"),
    # 5. lấy lại class FileIO gốc qua một stream đang mở
    ("type-of-stdout-buffer",
     "type(__import__('sys').__stdout__.buffer)(P, 'wb')"),
])
def test_layer_a_bypasses_are_caught_by_audit_hook(tmp_path, label, expr):
    target = tmp_path / f"{label}.out"
    out = _run_locked(f"""
        P = {str(target)!r}
        try:
            {expr}
            print("LOT")
        except Exception as e:
            print("CHAN:" + type(e).__name__)
    """)
    assert out.startswith("CHAN:"), f"{label}: không chặn — {out}"
    assert not target.exists(), f"{label}: SANDBOX ESCAPE"


def test_audit_hook_blocks_reading_dotenv():
    """Đường ĐỌC bí mật qua class FileIO gốc — lớp A không với tới được."""
    out = _run_locked("""
        import sys
        Raw = type(sys.__stdout__.buffer)
        for t in ('.env', '.env.example', '/etc/hostname'):
            try:
                Raw(t, 'rb').read(32); print("LOT:" + t); break
            except Exception:
                continue
        else:
            print("CHAN")
    """)
    assert out == "CHAN", f"đọc được file ngoài prefix: {out}"


def test_audit_hook_is_installed_and_unremovable():
    """Hook phải được cài (lockdown báo lại) và không có đường gỡ — đó chính
    là lý do chọn PEP 578 thay vì tiếp tục setattr."""
    out = _run_locked("""
        import sys
        st = {}
        print("HOOK=" + str(getattr(__import__('builtins'),
              rt.LOCKED_MARKER + '_audit', False)))
    """)
    assert "HOOK=True" in out
    assert not hasattr(sys, "removeaudithook")     # CPython cố ý không có


def test_audit_hook_allows_legit_work():
    """Không được chặn tay: import mới, pandas, và rolling.apply(lambda)."""
    out = _run_locked("""
        import email.mime.text, xml.dom.minidom, json, csv
        s = pd.Series(np.arange(300.0))
        v = s.rolling(20).mean().ewm(span=5).std().fillna(0).iloc[-1]
        r = s.rolling(10).apply(lambda w: float(w.max() - w.min()), raw=False)
        print(f"OK {round(float(v), 2)} {round(float(r.iloc[-1]), 2)}")
    """)
    assert out.startswith("OK "), out


def test_import_listing_not_over_blocked():
    """`os.listdir`/`scandir`/`glob` CỐ Ý không chặn — cơ chế import cần
    chúng, mà chúng chỉ liệt kê TÊN (nội dung đã khoá ở sự kiện `open`).
    Chặn nhầm là gãy import (đã dính khi thử)."""
    assert "os.listdir" not in rt._DENY_EVENTS
    assert "os.scandir" not in rt._DENY_EVENTS
    out = _run_locked("import os; print('N=' + str(len(os.listdir('.')) > 0))")
    assert out == "N=True", out

def test_import_without_cached_pyc_still_works(tmp_path):
    """Máy user (Windows) đỏ 2 test 'công việc hợp lệ': import một module
    CHƯA có `.pyc` khiến Python `mkdir __pycache__` + ghi `.pyc`, mà chính
    sách cấm mọi thao tác ghi → import CHẾT. Sandbox Linux không thấy vì
    stdlib đã cache sẵn. Thuốc: `sys.dont_write_bytecode = True` ngay trong
    lockdown() (không phụ thuộc biến môi trường)."""
    mod = tmp_path / "freshmod_for_test.py"
    mod.write_text("VALUE = 4242\n", encoding="utf-8")

    out = _run_locked(f"""
        import sys
        sys.path.insert(0, {str(tmp_path)!r})
        import freshmod_for_test as m
        print("OK " + str(m.VALUE))
    """)

    assert out == "OK 4242", out
    assert not (tmp_path / "__pycache__").exists()   # không ghi gì ra đĩa


def test_lockdown_disables_bytecode_writing():
    out = _run_locked("import sys; print('DWB=' + str(sys.dont_write_bytecode))")
    assert out == "DWB=True", out
