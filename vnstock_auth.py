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
    Create a stock instance with the correct API tier.

    Prefers vnstock_data (Sponsor) over vnstock (free) when available.
    vnstock warns: "Chỉ nhập API key trên vnstock bản free sẽ KHÔNG
    mở khóa được giới hạn."

    Always call this instead of Vnstock().stock() directly.
    """
    ensure_api_key()
    if _HAS_VNSTOCK_DATA:
        try:
            from vnstock_data import Equity
            return Equity().stock(ticker, source=source)
        except Exception:
            pass
    # Fallback to vnstock free
    from vnstock import Vnstock
    return Vnstock().stock(symbol=ticker, source=source)


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
