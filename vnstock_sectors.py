"""Canonical custom sector groupings shared across the dashboard money-flow tab
and the brief/screener pipeline, so a custom group means exactly the same set of
tickers everywhere.

Pure / dependency-free on purpose — importable from both the Streamlit-bound
dashboard module and the headless screener/runner without pulling heavy deps.

To add a new family: append one (label, {tickers}) entry to _CUSTOM_GROUPS.
The order here is the display order when these groups are pinned to the front
of the sector tables. A ticker may belong to at most one group (enforced).
"""
from __future__ import annotations

# Ticker-based sector groups, checked BEFORE the normal industry mapping.
_CUSTOM_GROUPS: "tuple[tuple[str, frozenset[str]], ...]" = (
    # Vingroup ecosystem (VPL = Vinpearl, listed 2025).
    ("Họ VIN", frozenset({"VIC", "VHM", "VRE", "VPL"})),
    # "Họ M" — Gelex ecosystem & affiliates.
    ("Họ M", frozenset({"GEX", "EIB", "VIX", "VGC", "VSC", "GEE", "GEL"})),
)


def _build_lookup(groups) -> "dict[str, str]":
    """Flatten groups → {ticker: label}, rejecting a ticker in two groups."""
    lut: "dict[str, str]" = {}
    for label, family in groups:
        for tk in family:
            if tk in lut:
                raise ValueError(
                    f"ticker {tk} is in two custom sector groups "
                    f"({lut[tk]} and {label})")
            lut[tk] = label
    return lut


_TICKER_TO_GROUP = _build_lookup(_CUSTOM_GROUPS)

# Display order of the custom groups (pinned to the front of sector tables).
CUSTOM_SECTOR_ORDER = [label for label, _ in _CUSTOM_GROUPS]
# Every ticker that belongs to any custom group.
CUSTOM_FAMILY = frozenset(_TICKER_TO_GROUP)


def custom_sector_for(symbol: str) -> "str | None":
    """Return the custom sector label for a ticker, else None."""
    return _TICKER_TO_GROUP.get(symbol)
