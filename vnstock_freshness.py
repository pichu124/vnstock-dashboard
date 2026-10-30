"""vnstock_freshness.py — Data staleness badge for dashboard tabs.

Renders a small inline badge showing how old a cached file is, with
color hint when data is stale.

Usage in a tab:
    from vnstock_freshness import render_freshness_row
    render_freshness_row([("Market overview", MARKET_OVERVIEW_PATH, 24)])
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dashboard.theme import TOKENS as _T, rgba as _rgba


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)} phút"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} giờ"
    return f"{seconds / 86400:.1f} ngày"


def file_age_seconds(path: Path | str) -> float | None:
    """Return age in seconds, or None if file does not exist."""
    p = Path(path)
    if not p.exists():
        return None
    return datetime.now().timestamp() - p.stat().st_mtime


def freshness_color(age_seconds: float, stale_seconds: float) -> str:
    """Màu token (P5 giao diện): xanh còn tươi, hổ phách sắp cũ (≥70%), đỏ đã cũ."""
    if age_seconds >= stale_seconds:
        return _T["down"]
    if age_seconds >= stale_seconds * 0.7:
        return _T["warn"]
    return _T["up"]


def freshness_html(
    label: str,
    path: Path | str,
    stale_seconds: float = 24 * 3600,
) -> str:
    """Return a small HTML badge string for inline display."""
    age = file_age_seconds(path)
    if age is None:
        return (
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
            f'background:{_T["border"]};color:{_T["text_muted"]};font-size:11px;'
            f'font-family:\'IBM Plex Sans\',sans-serif">'
            f'{label}: <b>chưa có data</b></span>'
        )
    color = freshness_color(age, stale_seconds)
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{_rgba(color, 0.1)};border:1px solid {color};'
        f'color:{color};font-size:11px;'
        f'font-family:\'IBM Plex Sans\',sans-serif">'
        f'{label}: <b>{_format_age(age)}</b> trước</span>'
    )




def render_freshness_row(items: list[tuple[str, Path | str, float]]) -> None:
    """Render multiple badges side by side.

    items: list of (label, path, stale_seconds) tuples.
    """
    try:
        import streamlit as st
    except ImportError:
        return
    if not items:
        return
    badges = " &nbsp; ".join(
        freshness_html(label, path, stale) for label, path, stale in items
    )
    st.markdown(
        f'<div style="margin:4px 0 12px 0">{badges}</div>',
        unsafe_allow_html=True,
    )
