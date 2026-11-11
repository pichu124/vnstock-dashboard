"""
vnstock_auth.py — Tài khoản Vnstock + nguồn dữ liệu + mặt tiền dữ liệu (vnstock thế hệ 6)
==========================================================================================

Thế hệ 6 (`vnstock` 6.x + `vnstock-oapi`) KHÔNG có nguồn mặc định: mọi lệnh gọi dữ liệu đọc Open API
của một nguồn MÀ USER CHỌN, bằng khoá của chính user. Chọn nguồn ở ĐÚNG MỘT CHỖ là file này, qua
biến môi trường (đặt trong `.env`):

    VNSTOCK_SOURCE=<nguồn>[,<nguồn dự phòng>…]       # mọi nhóm dữ liệu, nguồn ưu tiên trước
    VNSTOCK_SOURCE_ROUTES=<route>=<nguồn>[,…];…      # ghi đè theo nhóm, vd "fundamental.equity.*=<nguồn BCTC>"

Chưa đặt ⇒ không có luật nguồn ⇒ mọi lệnh gọi ném `InputError` mã `VNSTOCK_INPUT_SOURCE` (có kiểu, không
trả bảng rỗng). Code dự án KHÔNG được ghi tên nguồn vào từng lệnh gọi.

Tài khoản Vnstock: thế hệ 6 dùng chung kho khoá mã hoá `~/.vnstock/auth/` với thế hệ 5 và tự nhập
`~/.vnstock/api_key.json` của dòng cũ lần đầu chạy. Kiểm bằng `vnstock status`; user tự chạy
`vnstock login` nếu chưa nhận gói. File này không đăng nhập, không đọc, không in khoá.

Khoá của nguồn dữ liệu: user tự cất bằng `vnstock keys set <nguồn>` (keyring) — `vnstock-oapi` tự đọc.

Mặt tiền `get_vnstock(ticker)` giữ cách gọi cũ của dự án (`.quote.history`, `.company.*`,
`.listing.*`, `.finance.*`) nhưng bên trong gọi `Market` / `Reference` / `Fundamental` thế hệ 6.
Tính năng thế hệ 6 không có (vd `company.news`, `company.capital_history`) KHÔNG được bịa: lệnh gọi
ném `UnsupportedError` của chính vnstock, chỗ gọi xử lý như lỗi nguồn.

Cảnh báo `SchemaChangeWarning` (bảng khác thế hệ 5) KHÔNG được tắt: `keep_schema_warnings()` đặt lại
bộ lọc sau mọi `warnings.filterwarnings("ignore")` toàn cục của dự án.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_API_KEY = os.getenv("VNSTOCK_API_KEY", "").strip()

SOURCE_ENV = "VNSTOCK_SOURCE"
ROUTES_ENV = "VNSTOCK_SOURCE_ROUTES"

# Mã chỉ số mà dự án gọi qua `.quote.history` — thế hệ 6 đọc chỉ số ở `Market().index(...)`,
# cổ phiếu ở `Market().equity(...)`.
INDEX_SYMBOLS = frozenset({
    "VNINDEX", "VN30", "VN100", "VNMID", "VNSML", "VNALL", "VNXALL",
    "HNXINDEX", "HNX30", "UPCOMINDEX", "HNXUPCOMINDEX", "UPCOM",
})

_SOURCES_DONE = False


def keep_schema_warnings() -> None:
    """Giữ `SchemaChangeWarning` hiện ra dù module đã `warnings.filterwarnings("ignore")`.

    Bộ lọc thêm SAU đứng TRƯỚC trong danh sách ⇒ luật "default" này thắng luật "ignore" chung.
    """
    try:
        from vnstock.errors import SchemaChangeWarning
    except Exception:          # chưa cài vnstock (CI tối thiểu) — không có gì để giữ
        return
    warnings.filterwarnings("default", category=SchemaChangeWarning)


def _parse_names(raw: str) -> list[str]:
    return [n.strip() for n in (raw or "").split(",") if n.strip()]


def parse_routes(raw: str) -> list[tuple[str, list[str]]]:
    """`"fundamental.equity.*=a;market.equity.quote=b,c"` → [(route, [nguồn…]), …]. Hàm thuần."""
    out: list[tuple[str, list[str]]] = []
    for part in (raw or "").split(";"):
        if "=" not in part:
            continue
        route, names = part.split("=", 1)
        route, picked = route.strip(), _parse_names(names)
        if route and picked:
            out.append((route, picked))
    return out


def configure_sources(force: bool = False) -> dict:
    """Áp luật nguồn từ `.env` vào `vnstock.sources` (một lần mỗi tiến trình). Trả tóm tắt đã áp."""
    global _SOURCES_DONE
    summary = {"default": _parse_names(os.getenv(SOURCE_ENV, "")),
               "routes": parse_routes(os.getenv(ROUTES_ENV, ""))}
    if _SOURCES_DONE and not force:
        return summary
    try:
        import vnstock
    except Exception:
        return summary
    rules = ([("*", summary["default"])] if summary["default"] else []) + summary["routes"]
    for route, names in rules:
        try:
            vnstock.sources.use(*names, route=route)
        except Exception as e:  # tên nguồn/route sai trong .env ⇒ báo MỘT lần, không sập import
            import sys
            print(f"[vnstock_auth] ⚠ bỏ luật nguồn {route}={','.join(names)} "
                  f"({type(e).__name__}: {e}) — sửa {SOURCE_ENV}/{ROUTES_ENV} trong .env",
                  file=sys.stderr)
    _SOURCES_DONE = True
    return summary


def sources_configured() -> bool:
    return bool(_parse_names(os.getenv(SOURCE_ENV, "")) or parse_routes(os.getenv(ROUTES_ENV, "")))


def get_api_key() -> str:
    """Khoá tài khoản Vnstock trong `.env` (chỉ để biết có hay không — không bao giờ in ra)."""
    return _API_KEY


def has_sponsor_package() -> bool:
    """Dòng cũ có gói `vnstock_data` riêng; thế hệ 6 là MỘT gói `vnstock`, gói quyền do tài khoản quyết."""
    return False


def ensure_api_key() -> bool:
    """Chuẩn bị trước khi gọi dữ liệu: áp luật nguồn. Trả True nếu `.env` có khoá tài khoản.

    Thế hệ 6 tự đọc kho khoá `~/.vnstock/auth/` (hoặc biến `VNSTOCK_API_KEY`); không gọi đăng nhập ở đây.
    """
    configure_sources()
    keep_schema_warnings()
    return bool(_API_KEY)


# ── Mặt tiền dữ liệu (giữ cách gọi cũ của dự án) ───────────────────────────────

def is_index_symbol(symbol: str) -> bool:
    return str(symbol or "").strip().upper() in INDEX_SYMBOLS


def is_futures_symbol(symbol: str) -> bool:
    """HĐTL VN30: tên thân thiện (VN30F1M…), mã theo kỳ hạn (VN30F2512) hoặc mã KRX (41I1…).
    Thế hệ 6 đọc HĐTL ở `Market().futures(...)` — route cổ phiếu không đổi mã."""
    s = str(symbol or "").strip().upper()
    return s.startswith("VN30F") or s.startswith("41I")


def naive_local_time(df, column: str = "time", daily: bool = False):
    """Cột thời gian có múi giờ (thế hệ 6: bar ngày lúc 07:00 giờ VN) → giờ VN KHÔNG múi như dòng cũ.

    `daily=True` ⇒ chuẩn hoá về 00:00 để khớp kho bar ngày.
    """
    import pandas as pd
    if df is None or getattr(df, "empty", True) or column not in df.columns:
        return df
    out = df.copy()
    t = pd.to_datetime(out[column])
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert("Asia/Ho_Chi_Minh").dt.tz_localize(None)
    if daily:
        t = t.dt.normalize()
    out[column] = t
    return out


class _Quote:
    __slots__ = ("_symbol",)

    def __init__(self, symbol: str) -> None:
        self._symbol = str(symbol).strip().upper()

    def _node(self):
        from vnstock import Market
        m = Market()
        if is_index_symbol(self._symbol):
            return m.index(self._symbol)
        if is_futures_symbol(self._symbol):
            return m.futures(self._symbol)
        return m.equity(self._symbol)

    def history(self, start=None, end=None, interval: str = "1D", **kwargs):
        """Bar giá: `Market().equity(s).ohlcv` (chỉ số: `Market().index(s).ohlcv`), thời gian giờ VN không múi."""
        kwargs.pop("show_log", None)
        kwargs.pop("source", None)          # nguồn chọn ở configure_sources, không theo lệnh gọi
        ensure_api_key()
        df = self._node().ohlcv(start=start, end=end, interval=interval, **kwargs)
        return naive_local_time(df, daily=str(interval).upper() in ("1D", "D", "DAY"))


class _Delegate:
    """Chuyển thẳng mọi lệnh gọi sang nút thế hệ 6; bỏ hai tham số chỉ dòng cũ có (`show_log`, `source`)."""
    __slots__ = ("_node",)

    def __init__(self, node) -> None:
        self._node = node

    def __getattr__(self, name):
        target = getattr(self._node, name)
        if not callable(target):
            return target

        def call(*args, **kwargs):
            kwargs.pop("show_log", None)
            kwargs.pop("source", None)
            if "dropna" in kwargs:                      # đổi tên từ vnstock_data 3.2.8
                kwargs["drop_empty"] = kwargs.pop("dropna")
            ensure_api_key()
            return target(*args, **kwargs)
        return call


class _Listing:
    """`symbols_by_group` → `Reference().index(g).members()` (trả Series mã như dòng cũ);
    `symbols_by_exchange` / `all_symbols` → `Reference().equity.list()`."""

    def symbols_by_group(self, group: str = "VN30", **_):
        from vnstock import Reference
        ensure_api_key()
        df = Reference().index(str(group).upper()).members()
        if df is None or df.empty or "symbol" not in df.columns:
            import pandas as pd
            return pd.Series([], dtype=object, name="symbol")
        return df["symbol"].astype(str).str.upper().reset_index(drop=True)

    def symbols_by_exchange(self, **kwargs):
        from vnstock import Reference
        kwargs.pop("show_log", None)
        kwargs.pop("source", None)
        ensure_api_key()
        return Reference().equity.list(**kwargs)

    def all_symbols(self, **kwargs):
        return self.symbols_by_exchange(**kwargs)


def get_vnstock(ticker: str = "VCB", source: str | None = None):
    """Đối tượng có `.quote / .company / .listing / .finance` trên API thế hệ 6.

    `source` giữ chỉ để tương thích chữ ký cũ và BỊ BỎ QUA: tên nguồn dòng cũ ("VCI", "KBS"…) không
    mang sang thế hệ 6; nguồn chọn MỘT chỗ ở `configure_sources()`.
    """
    ensure_api_key()
    return _StockShim(ticker)


class _StockShim:
    __slots__ = ("_symbol",)

    def __init__(self, symbol: str) -> None:
        self._symbol = str(symbol).strip().upper()

    @property
    def quote(self) -> _Quote:
        return _Quote(self._symbol)

    @property
    def company(self) -> _Delegate:
        from vnstock import Reference
        return _Delegate(Reference().company(self._symbol))

    @property
    def listing(self) -> _Listing:
        return _Listing()

    @property
    def finance(self) -> _Delegate:
        from vnstock import Fundamental
        return _Delegate(Fundamental().equity(self._symbol))


# Áp luật nguồn ngay khi import (không gọi mạng); lỗi cấu hình hiện ra ở lệnh gọi dữ liệu đầu tiên.
try:
    configure_sources()
except Exception as _e:  # tên nguồn sai trong .env ⇒ vnstock ném InputError — báo một lần, không chặn import
    import sys as _sys
    print(f"[vnstock_auth] ⚠ cấu hình nguồn lỗi ({type(_e).__name__}: {_e}) — sửa {SOURCE_ENV}/{ROUTES_ENV} trong .env",
          file=_sys.stderr)
keep_schema_warnings()
