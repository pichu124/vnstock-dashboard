"""
vnstock_auth.py — Centralized API key management
==================================================
Ensures the Golden/Sponsor API key from .env is ALWAYS active,
even after vnstock/vnstock_data imports that auto-register free keys.

Usage:
    from vnstock_auth import ensure_api_key, get_api_key, get_vnstock

    ensure_api_key()           # Call after any vnstock import
    key = get_api_key()        # Get the .env key
    stock = get_vnstock(ticker) # Vnstock instance with key applied
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env once at import time
load_dotenv(Path(__file__).parent / ".env")

_API_KEY = os.getenv("VNSTOCK_API_KEY", "").strip()


def get_api_key() -> str:
    """Return the API key from .env."""
    return _API_KEY


def ensure_api_key() -> bool:
    """
    (Re-)apply the Golden API key from .env.

    Call this AFTER importing vnstock/vnstock_data modules,
    because those imports can auto-register a new free-tier key
    that overwrites your Golden key.

    Returns True if key was applied, False if no key in .env.
    """
    if not _API_KEY:
        return False

    # 1. Always set env var (some vnstock code paths read from env)
    os.environ["VNSTOCK_API_KEY"] = _API_KEY

    # 2. Apply via auth module
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
    Create a Vnstock().stock() instance with the Golden API key applied.

    Always call this instead of Vnstock().stock() directly to ensure
    the correct API tier is used.
    """
    ensure_api_key()
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
