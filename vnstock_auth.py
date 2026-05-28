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
from pathlib import Path
from dotenv import load_dotenv

# Load .env once at import time
load_dotenv(Path(__file__).parent / ".env")

_API_KEY = os.getenv("VNSTOCK_API_KEY", "").strip()

# Detect if vnstock_data (Sponsor) is available
_HAS_VNSTOCK_DATA = False
try:
    import vnstock_data  # noqa: F401
    _HAS_VNSTOCK_DATA = True
except ImportError:
    pass


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

    # Always set env var (some code paths read from env)
    os.environ["VNSTOCK_API_KEY"] = _API_KEY

    # Only call change_api_key for vnstock FREE (no Sponsor package)
    if not _HAS_VNSTOCK_DATA:
        try:
            from vnstock.core.utils.auth import change_api_key
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
