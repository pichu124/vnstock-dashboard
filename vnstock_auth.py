"""
vnstock_auth.py — Centralized API key management
==================================================
Ensures the Golden/Sponsor API key from .env is ALWAYS active.

CRITICAL: When vnstock_data (Sponsor) is installed, we must NOT call
vnstock.core.utils.auth.change_api_key() — that function only applies
to vnstock FREE and will OVERWRITE the Sponsor device registration,
downgrading to Community tier.

vnstock_data manages its own authentication via the GUI installer
(vnstock-installer). The API key is registered per-device and stored
internally. We only set the env var as a fallback signal.

Usage:
    from vnstock_auth import ensure_api_key, get_api_key, get_vnstock

    ensure_api_key()           # Call after any vnstock import
    key = get_api_key()        # Get the .env key
    stock = get_vnstock(ticker) # Stock instance with key applied
"""

import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

# Suppress the noisy sponsor-detection UserWarning from vnstock/__init__.py.
# The warning fires on every `import vnstock` and clutters terminal output.
warnings.filterwarnings("ignore", category=UserWarning, module=r"vnstock")

# Load .env once at import time
load_dotenv(Path(__file__).parent / ".env")

_API_KEY = os.getenv("VNSTOCK_API_KEY", "").strip()

# Detect if Sponsor tier package is available.
# The Sponsor SDK ships under two names historically:
#   - `vnstock_data` (older, being phased out)
#   - `vnii`         (newer, vnstocks.com/api/simple index)
# Either one being importable is sufficient to mark the device as Sponsor.
# Catch BaseException because broken installs (e.g. vnstock_data ↔ vnstock
# version mismatch raising ImportError on `_GROUP_CODE`) shouldn't crash
# the whole dashboard, but we ALSO shouldn't silently downgrade to free —
# if the package is present but broken, log the error so user can fix it.
_HAS_VNSTOCK_DATA = False
_SPONSOR_IMPORT_ERROR: Exception | None = None
for _mod_name in ("vnii", "vnstock_data"):
    try:
        __import__(_mod_name)
        _HAS_VNSTOCK_DATA = True
        break
    except ImportError:
        continue
    except Exception as _e:
        # Package present but import fails (version mismatch, missing dep).
        # Save the first such error; if no working sponsor package found
        # we'll log it once during ensure_api_key().
        if _SPONSOR_IMPORT_ERROR is None:
            _SPONSOR_IMPORT_ERROR = _e
        # Treat broken package as "installed" so we don't downgrade.
        _HAS_VNSTOCK_DATA = True
        break


def get_api_key() -> str:
    """Return the API key from .env."""
    return _API_KEY


def has_sponsor_package() -> bool:
    """Return True if vnstock_data (Sponsor) is installed."""
    return _HAS_VNSTOCK_DATA


def ensure_api_key() -> bool:
    """
    Ensure the correct API key is active.

    - When vnstock_data (Sponsor) is installed: only set env var.
      Do NOT call change_api_key() — it overwrites Sponsor auth
      with a Community registration.
    - When only vnstock (free) is available: call change_api_key()
      to apply the key for the free tier.

    Returns True if key was applied, False if no key in .env.
    """
    if not _API_KEY:
        return False

    # Warn once if a sponsor package is installed but broken
    global _SPONSOR_IMPORT_ERROR
    if _SPONSOR_IMPORT_ERROR is not None:
        import sys as _sys
        print(
            f"[vnstock_auth] ⚠ Sponsor package installed but broken: "
            f"{type(_SPONSOR_IMPORT_ERROR).__name__}: {_SPONSOR_IMPORT_ERROR}\n"
            f"  → Upgrade with: pip install --upgrade --extra-index-url "
            f"https://vnstocks.com/api/simple vnii vnstock-installer",
            file=_sys.stderr,
        )
        _SPONSOR_IMPORT_ERROR = None   # warn only once per process

    # Always set env var (some code paths read from env)
    os.environ["VNSTOCK_API_KEY"] = _API_KEY

    # Only call change_api_key for vnstock FREE (no Sponsor package)
    if not _HAS_VNSTOCK_DATA:
        try:
            from vnstock.core.utils.auth import change_api_key
            # change_api_key() prints "✓ API key đã được cập nhật" + sponsor
            # promo banner on every call. Suppress stdout so the user's
            # terminal stays clean when the key is just being re-applied.
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                change_api_key(_API_KEY)
        except ImportError:
            pass
        except Exception:
            pass

    return True


def get_vnstock(ticker: str = "VCB", source: str = "VCI"):
    """
    Return a stock-like object exposing .quote / .company / .listing.

    Migration (vnstock 4.x deprecated `Vnstock().stock(...)` on 31/08/2025).
    We now lazily build the new per-domain classes (Quote, Company, Listing)
    and expose them via a shim, so callsites using
    `get_vnstock(t).quote.history(...)` keep working without touching every
    file. Old `Vnstock()` class is used only as a last-resort fallback.
    """
    ensure_api_key()
    return _StockShim(symbol=ticker, source=source)


class _StockShim:
    """Lazy-loading wrapper that exposes .quote / .company / .listing
    via the new `vnstock.api.*` modules (vnstock 4.x+)."""

    __slots__ = ("_symbol", "_source", "__quote", "__company", "__listing")

    def __init__(self, symbol: str, source: str) -> None:
        self._symbol = symbol
        self._source = source
        self.__quote = None
        self.__company = None
        self.__listing = None

    @property
    def quote(self):
        if self.__quote is None:
            try:
                from vnstock.api.quote import Quote  # type: ignore
            except ImportError:
                from vnstock import Quote  # type: ignore
            self.__quote = Quote(symbol=self._symbol, source=self._source)
        return self.__quote

    @property
    def company(self):
        if self.__company is None:
            try:
                from vnstock.api.company import Company  # type: ignore
                self.__company = Company(symbol=self._symbol, source=self._source)
            except ImportError:
                # Last-resort fallback to old API (prints deprecation notice)
                from vnstock import Vnstock  # type: ignore
                self.__company = Vnstock().stock(
                    symbol=self._symbol, source=self._source
                ).company
        return self.__company

    @property
    def listing(self):
        if self.__listing is None:
            try:
                from vnstock.api.listing import Listing  # type: ignore
                self.__listing = Listing(source=self._source)
            except ImportError:
                from vnstock import Vnstock  # type: ignore
                self.__listing = Vnstock().stock(
                    symbol=self._symbol, source=self._source
                ).listing
        return self.__listing


def check_tier() -> str:
    """Check current API tier. Returns 'golden', 'silver', 'bronze', or 'community'."""
    ensure_api_key()
    try:
        from vnstock.core.utils.auth import check_status
        status = str(check_status()).lower()
        for tier in ("golden", "silver", "bronze"):
            if tier in status:
                return tier
    except Exception:
        pass
    return "community"
