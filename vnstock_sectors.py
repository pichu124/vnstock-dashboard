"""Canonical custom sector groupings shared across the dashboard money-flow tab
and the brief/screener pipeline, so a custom group like "Họ VIN" means exactly
the same set of tickers everywhere.

Pure / dependency-free on purpose — importable from both the Streamlit-bound
dashboard module and the headless screener/runner without pulling heavy deps.
"""
from __future__ import annotations

# The Vingroup ecosystem, grouped OUT of its members' listed industries
# (BĐS / bán lẻ / du lịch) into one family sector. VPL = Vinpearl (listed 2025).
VIN_FAMILY = frozenset({"VIC", "VHM", "VRE", "VPL"})
VIN_SECTOR = "Họ VIN"


def vin_sector_for(symbol: str) -> "str | None":
    """Return VIN_SECTOR for a Vingroup-ecosystem ticker, else None."""
    return VIN_SECTOR if symbol in VIN_FAMILY else None
