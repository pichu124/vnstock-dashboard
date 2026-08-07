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
    "SandboxViolation", "lockdown", "install_audit_hook",
    "scrub_secrets_from_env", "serve", "minimal_env", "LOCKED_MARKER",
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
        "execv execve execvp execvpe spawnv spawnve spawnl spawnle spawnvp "
        "spawnvpe spawnlp spawnlpe posix_spawn posix_spawnp fork "
        "forkpty kill killpg putenv unsetenv open fdopen chdir setuid "
        "setgid umask mkfifo mknod"
    ),
    "posix": (
        "system popen remove unlink rename replace rmdir mkdir chmod chown "
        "link symlink truncate execv execve fork kill open putenv posix_spawn "
        "posix_spawnp write"
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

# ── `FileIO`: khoá được mà không giết cơ chế import ───────────────────────
# Tự dò 06/08 sau khi dựng tầng này: `io.FileIO('x','w')` ĐỌC VÀ GHI được
# file mà KHÔNG đi qua `open` → thoát sạch (đường đọc thẳng `.env`!).
# Nhưng `_io.FileIO`/`_io.open_code` CHÍNH LÀ thứ importlib dùng để nạp
# module — chặn cứng thì không `import` được gì nữa (đã đo).
# Nên: cổng theo CHÍNH SÁCH — chỉ cho ĐỌC file kiểu module, cấm mọi thứ khác.
_IMPORT_SUFFIXES = (".py", ".pyc", ".pyo", ".pyd", ".so", ".dll", ".zip",
                    ".egg", ".whl")


def _guarded_fileio(real, label: str, takes_mode: bool = True):
    """Bọc `FileIO`/`open_code`: chỉ lọt khi ĐỌC file module.

    `takes_mode=False` cho `open_code(path)` — hàm này CHỈ nhận đường dẫn,
    truyền thêm mode vào là TypeError làm chết cơ chế import (đã dính).
    """
    def _factory(file, mode="r", *args, **kwargs):
        path = str(file)
        writing = any(c in str(mode) for c in "wax+")
        if isinstance(file, int) or writing or not path.endswith(_IMPORT_SUFFIXES):
            raise SandboxViolation(
                f"sandbox: `{label}` chỉ được ĐỌC file module — từ chối "
                f"{'ghi' if writing else 'đọc'} {path[:80]!r}")
        return real(file, mode, *args, **kwargs) if takes_mode else real(file)
    return _factory


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


# ── LỚP B: audit hook (PEP 578) — hàng rào THẬT, ở tầng C ─────────────────
# Vòng đối kháng thứ 4 phá sạch lớp A (setattr lên module object) bằng 5
# đường, tất cả cùng một bản chất: **không thể GIẤU thứ gì khỏi code Python
# chạy cùng tiến trình**:
#   1. `del sys.modules['posix']; import posix` → module C dựng lại NGUYÊN BẢN
#   2. `os.posix_spawn(...)`                     → tên bị bỏ sót trong deny list
#   3. `_io.open(...)`                           → cố ý không vá (sợ chết import)
#   4. `tokenize._builtin_open` / `bz2._builtin_open` / `tarfile.bltn_open` /
#      `numpy.lib._datasource._open` → giữ THAM CHIẾU tới `open` GỐC từ lúc
#      import, setattr sau đó không đụng tới được
#   5. `type(sys.__stdout__.buffer)`             → lấy lại class FileIO gốc
#
# Audit hook khác về CHẤT: sự kiện được CPython phát ra TỪ BÊN TRONG chính
# primitive (C level), nên mọi đường trên đều đi qua nó — tham chiếu cũ,
# module vừa import lại, class lấy qua type(), đều như nhau. Và
# `sys.addaudithook` KHÔNG CÓ API gỡ: cài rồi thì code trong tiến trình
# không tự tháo được. Đo thực nghiệm: chặn 8/8 đường, pandas + import vẫn
# chạy, 300 phép rolling tốn 0.03s (chi phí ~0 vì số học không phát sự kiện).
_DENY_EVENTS = frozenset("""
    os.system os.exec os.posix_spawn os.spawn os.fork os.forkpty
    os.kill os.killpg os.remove os.rename os.rmdir os.mkdir os.chmod
    os.chown os.link os.symlink os.truncate os.putenv os.unsetenv
    os.setuid os.setgid os.startfile os.chdir
    os.add_dll_directory
    subprocess.Popen
    socket.__new__ socket.bind socket.connect socket.getaddrinfo
    socket.sendto socket.gethostbyname
    ctypes.dlopen ctypes.dlsym ctypes.dlsym/handle ctypes.call_function
    ctypes.set_errno ctypes.get_errno ctypes.create_string_buffer
    shutil.copyfile shutil.copymode shutil.copystat shutil.move
    shutil.rmtree shutil.unpack_archive shutil.make_archive
    webbrowser.open urllib.Request
    mmap.__new__ fcntl.fcntl fcntl.ioctl
    tempfile.mkstemp tempfile.mkdtemp
""".split())
# CỐ Ý KHÔNG chặn: `os.listdir`/`os.scandir`/`glob.glob` — cơ chế import dùng
# chúng để quét thư mục module, mà bản thân chúng chỉ LIỆT KÊ TÊN, không đọc
# được nội dung (đường đọc đã khoá ở sự kiện `open`). Chặn thì gãy import.
# Cũng không chặn `exec`/`compile`/`marshal.loads`: worker PHẢI exec code
# chiến lược, và importlib giải mã .pyc bằng marshal. Chúng không tự cấp
# thêm năng lực nào — mọi năng lực thật đều đi qua các sự kiện phía trên.


def _read_allowed(path: str) -> bool:
    """Chỉ cho ĐỌC file của thư viện: file module (.py/.pyc/.so…) hoặc bất kỳ
    file nào nằm trong prefix Python (stdlib + site-packages, gồm cả dữ liệu
    kèm theo như zoneinfo). Thư mục repo KHÔNG nằm trong prefix nên `.env`
    vẫn bị chặn — đó là điểm mấu chốt."""
    if path.endswith(_IMPORT_SUFFIXES):
        return True
    prefixes = [p for p in (getattr(sys, "prefix", None),
                            getattr(sys, "base_prefix", None),
                            getattr(sys, "exec_prefix", None)) if p]
    prefixes.append(os.path.join(os.sep, "usr", "share", "zoneinfo"))
    return any(path.startswith(p + os.sep) for p in prefixes)


def _audit_hook(event: str, args) -> None:
    """Từ chối mọi năng lực nguy hiểm. KHÔNG được ném lỗi vì lý do khác —
    hook chạy trong MỌI thao tác được audit của tiến trình."""
    if event in _DENY_EVENTS:
        raise SandboxViolation(
            f"sandbox: sự kiện `{event}` bị chặn (audit hook)")
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if path is None:                      # open theo fd — không cho
            raise SandboxViolation("sandbox: `open` theo file descriptor bị chặn")
        p = str(path)
        writing = bool(mode and any(c in str(mode) for c in "wax+"))
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR
                                               | os.O_CREAT | os.O_APPEND):
            writing = True
        if writing:
            raise SandboxViolation(f"sandbox: cấm GHI file — {p[:80]!r}")
        if not _read_allowed(p):
            raise SandboxViolation(f"sandbox: cấm ĐỌC file — {p[:80]!r}")


def install_audit_hook() -> bool:
    """Cài hook (một chiều, không gỡ được). True nếu vừa cài."""
    if getattr(builtins, LOCKED_MARKER + "_audit", False):
        return False
    sys.addaudithook(_audit_hook)
    setattr(builtins, LOCKED_MARKER + "_audit", True)
    return True


def lockdown() -> dict:
    """Vô hiệu hoá năng lực nguy hiểm trong TIẾN TRÌNH HIỆN TẠI (một chiều).

    Hai lớp: (A) setattr đè hàm trên module object — thông báo lỗi thân
    thiện, bắt sớm; (B) audit hook PEP 578 — hàng rào THẬT ở tầng C, không
    gỡ được, bắt cả những đường lớp A không với tới (xem chú thích
    `_DENY_EVENTS`). Lớp A một mình đã bị red-team phá 5 đường; lớp B mới là
    thứ giữ được.

    CHỈ gọi trong tiến trình worker — gọi ở tiến trình chính sẽ làm hỏng
    dashboard/pipeline. Trả về thống kê để test soi.
    """
    if getattr(builtins, LOCKED_MARKER, False):
        return {"already": True}

    # Dọn bí mật TRƯỚC (xem docstring scrub_secrets_from_env)
    stats = {"functions": 0, "modules": 0,
             "env_scrubbed": scrub_secrets_from_env()}

    # Tắt ghi bytecode TRƯỚC khi khoá: import một module CHƯA có `.pyc` sẽ
    # `mkdir __pycache__` + ghi `.pyc`, mà chính sách cấm mọi thao tác ghi →
    # import CHẾT. Máy user (Windows) đỏ đúng 2 test "công việc hợp lệ" vì
    # vậy, còn sandbox Linux không thấy do stdlib đã cache sẵn .pyc.
    # `minimal_env()` cũng đặt PYTHONDONTWRITEBYTECODE=1, nhưng bảo đảm này
    # không được phụ thuộc vào env — ai gọi lockdown() cũng phải an toàn.
    sys.dont_write_bytecode = True

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

    # 1b. FileIO/open_code — đường ĐỌC-GHI file KHÔNG qua `open`. Cổng theo
    #     chính sách vì importlib cũng dùng chính chúng (xem _guarded_fileio).
    for ns_name in ("_io", "io"):
        mod = sys.modules.get(ns_name)
        if mod is None:
            continue
        for cls_name in ("FileIO", "open_code"):
            real = getattr(mod, cls_name, None)
            if real is None:
                continue
            try:
                setattr(mod, cls_name,
                        _guarded_fileio(real, f"{ns_name}.{cls_name}",
                                        takes_mode=cls_name == "FileIO"))
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

    # LỚP B cài SAU CÙNG: các setattr ở trên tự chúng phát sự kiện audit
    # (vd `object.__setattr__`), cài hook trước sẽ tự chặn chính mình.
    stats["audit_hook"] = install_audit_hook()
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
