"""vnstock_sandbox_runtime.py — khoá NĂNG LỰC cho tiến trình chạy chiến lược.

VÌ SAO CÓ FILE NÀY (audit + 3 vòng đối kháng 06/08/2026)
────────────────────────────────────────────────────────
Sandbox cũ lọc CÚ PHÁP (AST) trên một đối tượng pandas THẬT. Ba vòng red-team
cho thấy cách đó rò rỉ theo bản chất — bịt được lớp này thì lộ lớp khác:

  vòng 1  pd.io.common.os.system(...)        → chuỗi attribute toàn tên thường
  vòng 2  df.agg('to_csv', 0, path)          → tên method là CHUỖI, AST mù
  vòng 3  w = df.agg; w('to_csv', ...)       → bound method là object hạng nhất

Mỗi lần vá là một vòng đuổi bắt, và không có gì bảo đảm đã hết — bề mặt
pandas quá rộng, chưa kể bản mới có thể mở lại đường khác.

ĐỔI CÁCH ĐÁNH: thay vì hỏi "câu lệnh này có nguy hiểm không?", khoá thẳng
NĂNG LỰC của tiến trình: không mở được file, không gọi được shell, không mở
được socket. Lúc đó `df.to_csv(path)` thất bại ở ĐÚNG bước ghi file, bất kể
nó được gọi bằng cú pháp gì — trực tiếp, qua chuỗi, hay qua biến trung gian.

Điểm mạnh so với lọc cú pháp:
  * Không phụ thuộc hình dạng code → miễn nhiễm với các trò lách AST.
  * KHÔNG đụng tới API pandas → không sinh false positive (vá cú pháp vòng 1
    từng giết 6/12 chiến lược thật).
  * Bản pandas mới thêm API cũng không mở ra đường mới.

Bắt buộc chạy trong TIẾN TRÌNH RIÊNG: khoá `open` trong tiến trình chính sẽ
làm hỏng cả dashboard/pipeline. `vnstock_strategy.IsolatedExecutor` spawn
worker rồi gọi `lockdown()` ở đây trước khi chạy bất kỳ code chiến lược nào.

GIỚI HẠN (nói thẳng): đây vẫn là phòng thủ trong-tiến-trình, không phải
seccomp/container. Nó chặn mọi đường ĐÃ BIẾT ở tầng thư viện chuẩn Python.
Muốn cứng hơn nữa thì phải hạ quyền ở tầng OS (user riêng/AppContainer) —
việc lớn hơn nhiều, chưa làm.
"""
from __future__ import annotations

import builtins
import os
import re
import sys

__all__ = [
    "SandboxViolation", "lockdown", "scrub_secrets_from_env",
    "worker_main", "LOCKED_MARKER",
]

LOCKED_MARKER = "__vnstock_sandbox_locked__"


class SandboxViolation(RuntimeError):
    """Code chiến lược chạm tới năng lực bị khoá (file/shell/mạng)."""


def _denied(label: str):
    def _blocked(*args, **kwargs):
        raise SandboxViolation(
            f"sandbox: `{label}` bị khoá trong tiến trình chạy chiến lược "
            f"(không cho đụng file/shell/mạng)")
    _blocked.__name__ = f"blocked_{label.replace('.', '_')}"
    return _blocked


# Tên hàm bị khoá theo từng module. `posix`/`nt` là module C nằm DƯỚI `os` —
# bỏ sót thì `import posix; posix.system(...)` đi vòng qua được.
_MODULE_DENY = {
    "os": (
        "system popen remove unlink rename replace rmdir mkdir makedirs "
        "removedirs chmod chown link symlink truncate ftruncate startfile "
        "execv execve execvp execvpe spawnv spawnve spawnl spawnle fork "
        "forkpty kill killpg putenv unsetenv open fdopen chdir setuid "
        "setgid umask mkfifo mknod"
    ),
    "posix": (
        "system popen remove unlink rename replace rmdir mkdir chmod chown "
        "link symlink truncate execv execve fork kill open putenv"
    ),
    "nt": (
        "system popen remove unlink rename replace rmdir mkdir chmod link "
        "symlink truncate startfile execv execve spawnv kill open putenv"
    ),
    "shutil": (
        "copy copy2 copyfile copytree copyfileobj move rmtree make_archive "
        "unpack_archive chown"
    ),
    "subprocess": (
        "Popen run call check_call check_output getoutput getstatusoutput"
    ),
    "socket": "socket create_connection socketpair create_server",
    "webbrowser": "open open_new open_new_tab",
    "ctypes": "CDLL WinDLL OleDLL PyDLL cdll windll",
}

# `open` sống ở nhiều namespace: rebind ở builtins KHÔNG đổi io.open.
# CỐ Ý KHÔNG đụng `_io.open` — đó chính là hàm cơ chế import của CPython
# dùng; khoá nó thì `import` và lazy-import bên trong pandas chết theo
# (đã đo: mọi thứ hỏng ngay). `builtins.open` + `io.open` đã đủ chặn pandas
# ghi file, vì pandas gọi `open(...)` phân giải qua builtins.
_OPEN_NAMESPACES = ("builtins", "io")

# Method ghi/đổi file trên pathlib.Path — đường vòng phổ biến nhất của `open`.
_PATH_DENY = ("open write_text write_bytes unlink mkdir rmdir rename replace "
              "touch chmod symlink_to hardlink_to")

# Biến môi trường KHÔNG được để lọt vào tiến trình chạy code lạ. Kể cả khi
# mọi đường ghi file đã khoá, `os.environ` vẫn nằm sẵn trong RAM tiến trình
# con (kế thừa từ cha đã load .env) — dọn đi cho chắc.
_SECRET_ENV_RE = re.compile(
    r"(API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|_KEY$|SESSION)",
    re.IGNORECASE)


def scrub_secrets_from_env() -> int:
    """Xoá mọi biến môi trường trông như bí mật. Trả về số biến XOÁ ĐƯỢC THẬT.

    PHẢI gọi TRƯỚC khi khoá `os.*`: `del os.environ[k]` gọi xuống
    `os.unsetenv`, mà hàm đó nằm trong danh sách khoá — đảo thứ tự thì mọi
    lần xoá đều ném SandboxViolation rồi bị nuốt, hàm trả về con số ĐẸP mà
    thực tế không xoá được gì (bug đã dính khi đo lần đầu 06/08).
    """
    removed = 0
    for k in [k for k in list(os.environ) if _SECRET_ENV_RE.search(k)]:
        try:
            del os.environ[k]
            removed += 1
        except Exception:
            pass
    return removed


def lockdown() -> dict:
    """Vô hiệu hoá năng lực nguy hiểm trong TIẾN TRÌNH HIỆN TẠI (một chiều).

    CHỈ gọi trong tiến trình worker — gọi ở tiến trình chính sẽ làm hỏng
    dashboard/pipeline. Trả về thống kê để test soi.
    """
    if getattr(builtins, LOCKED_MARKER, False):
        return {"already": True}

    # Dọn bí mật TRƯỚC (xem docstring scrub_secrets_from_env)
    stats = {"functions": 0, "modules": 0,
             "env_scrubbed": scrub_secrets_from_env()}

    # 1. `open` ở mọi namespace nó cư trú
    for ns_name in _OPEN_NAMESPACES:
        mod = sys.modules.get(ns_name)
        if mod is None:
            continue
        try:
            setattr(mod, "open", _denied(f"{ns_name}.open"))
            stats["functions"] += 1
        except Exception:
            pass

    # 2. Hàm nguy hiểm theo module. Vá NGAY TRÊN module object nên mọi đường
    #    vòng tới nó (pd.io.common.os, import os, …) đều nhận bản đã khoá.
    for mod_name, names in _MODULE_DENY.items():
        mod = sys.modules.get(mod_name)
        if mod is None:
            try:
                mod = __import__(mod_name)
            except Exception:
                continue
        stats["modules"] += 1
        for fn_name in names.split():
            if not hasattr(mod, fn_name):
                continue
            try:
                setattr(mod, fn_name, _denied(f"{mod_name}.{fn_name}"))
                stats["functions"] += 1
            except Exception:
                pass

    # 3. pathlib.Path — API hướng đối tượng của cùng mấy năng lực trên
    try:
        import pathlib
        for meth in _PATH_DENY.split():
            if hasattr(pathlib.Path, meth):
                setattr(pathlib.Path, meth, _denied(f"Path.{meth}"))
                stats["functions"] += 1
    except Exception:
        pass

    setattr(builtins, LOCKED_MARKER, True)
    return stats


# ── Giao thức worker: pickle có tiền tố độ dài, qua stdin/stdout ──────────
# CỐ Ý dùng subprocess thay vì multiprocessing: `spawn` của multiprocessing
# RE-IMPORT `__main__` ở tiến trình con — chạy từ dashboard Streamlit thì
# `__main__` chính là script dashboard, con sẽ chạy lại cả app (hoặc đẻ
# tiếp worker). Pipe nhị phân thì không dính bẫy đó và giống nhau trên mọi OS.

def _send(stream, obj) -> None:
    import pickle as _pkl
    import struct as _st
    blob = _pkl.dumps(obj, protocol=_pkl.HIGHEST_PROTOCOL)
    stream.write(_st.pack("<Q", len(blob)))
    stream.write(blob)
    stream.flush()


def _recv(stream):
    import pickle as _pkl
    import struct as _st
    head = stream.read(8)
    if not head or len(head) < 8:
        return None
    (n,) = _st.unpack("<Q", head)
    buf = stream.read(n)
    if buf is None or len(buf) < n:
        return None
    return _pkl.loads(buf)


def serve(stdin=None, stdout=None) -> None:  # pragma: no cover - tiến trình con
    """Vòng lặp worker: khoá năng lực rồi phục vụ nhiều lần chạy.

    Một tiến trình phục vụ MỌI lần gọi (cache hàm signal đã compile theo
    code): backtest chạy hàng nghìn cửa sổ, dựng tiến trình mỗi lần thì
    Windows tốn ~0.5s/lần — chính lý do bản cũ phải chạy in-process và mất
    luôn cách ly.
    """
    rx = stdin if stdin is not None else sys.stdin.buffer
    tx = stdout if stdout is not None else sys.stdout.buffer

    # Nạp sẵn thư viện nặng TRƯỚC khi khoá — sau khoá vẫn import được (ta
    # không đụng `_io.open`), nhưng nạp trước thì lần chạy đầu khỏi chờ.
    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
        import vnstock_strategy  # noqa: F401
    except Exception:
        pass

    stats = lockdown()
    _send(tx, {"ready": True, "stats": stats})

    compiled: dict = {}          # code → hàm signal đã compile
    while True:
        req = _recv(rx)
        if req is None or req.get("stop"):
            break
        try:
            import pickle as _pkl
            code = req["code"]
            fn = compiled.get(code)
            if fn is None:
                fn = _compile_signal(code)
                compiled[code] = fn
            result = fn(_pkl.loads(req["df"]), req["params"])
            if not isinstance(result, dict):
                raise TypeError("signal() must return a dict")
            _send(tx, {"ok": True, "result": result})
        except Exception as e:
            _send(tx, {"ok": False,
                       "error": f"{type(e).__name__}: {str(e)[:300]}"})


def _compile_signal(code: str):
    """Validate AST + exec trong globals hạn chế → trả hàm `signal`.

    Dùng MỘT dict chung làm globals lẫn locals: tách 2 dict thì hàm phụ do
    chiến lược định nghĩa rơi vào locals, còn `signal` chỉ thấy globals →
    NameError khi gọi lẫn nhau (bẫy có sẵn ở `InProcessExecutor`).

    `df`/`params` đi qua THAM SỐ của signal() nên không cần nạp lại vào
    globals mỗi lần chạy — nhờ vậy compile 1 lần, chạy hàng nghìn cửa sổ.

    Import muộn: vnstock_strategy import module này, nên import ở đầu file sẽ
    thành vòng tròn.
    """
    from vnstock_strategy import _safe_globals, _validate_ast

    _validate_ast(code)                      # lớp 1 vẫn giữ (bắt sớm, rẻ)
    g = _safe_globals(None, {})
    exec(compile(code, "<strategy>", "exec"), g)
    fn = g.get("signal")
    if not callable(fn):
        raise ValueError("Strategy must define `signal(df, params)`")
    return fn


def minimal_env() -> dict:
    """Env TỐI THIỂU để dựng worker — KHÔNG kế thừa env của tiến trình cha.

    Cha đã `load_dotenv()` nên `os.environ` chứa toàn bộ API key/token. Chặn
    ngay từ khâu truyền env là chắc hơn dọn sau (`scrub_secrets_from_env`
    vẫn giữ làm lớp 2 phòng khi ai đó gọi lockdown ở tiến trình khác).
    """
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "COMSPEC", "WINDIR",
            "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG", "LC_ALL",
            "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONHASHSEED", "PATHEXT")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


if __name__ == "__main__":     # pragma: no cover - điểm vào tiến trình worker
    serve()
