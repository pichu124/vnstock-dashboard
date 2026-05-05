"""dashboard/news_tab.py — News tab for VNStock Dashboard.

Displays an aggregated news feed for all tracked market tickers.
News is fetched via vnstock (VCI → KBS fallback), cached to disk,
and made available to AI agents in brief & analysis contexts.
"""

from __future__ import annotations

import streamlit as st
from datetime import datetime, date, timedelta
import re
from urllib.parse import urljoin, urlparse

# VCI's company.news() returns `news_source_link` as a host-less path like
# "2026/02/<slug>-737-1404929.htm". The pattern (year/month + dash-separated
# numeric category + article id + .htm) is vietstock.vn's canonical layout —
# cafef.vn uses .chn URLs and a different ID scheme.
_DEFAULT_NEWS_BASE = "https://vietstock.vn/"
_VIETSTOCK_PATH_RE = re.compile(r"^/?\d{4}/\d{2}/.+-\d+-\d+\.htm$")


def _normalize_news_url(url: str) -> str:
    """Return an absolute URL pointing at the right publisher host.

    Handles three cases produced by vnstock + a stale-cache fix:
    1. Empty / scheme-less path → prepend default host.
    2. Already-absolute URL on the correct host → pass through.
    3. Old cached entries that were prefixed with cafef.vn (commit 9e5de41
       was wrong) but carry a vietstock-pattern path → rewrite host.
    """
    if not url or not url.strip():
        return ""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        if (
            parsed.netloc.endswith("cafef.vn")
            and _VIETSTOCK_PATH_RE.match(parsed.path)
        ):
            return f"https://vietstock.vn{parsed.path}"
        return url
    if url.startswith("//"):
        return "https:" + url
    return urljoin(_DEFAULT_NEWS_BASE, url.lstrip("/"))


def _fmt_age(date_str: str) -> str:
    """Human-readable age: 'Hôm nay 14:30', '2 ngày trước'.

    Returns 'Không rõ ngày' for unparseable input so the user can spot
    items with missing date metadata (instead of silent empty caption).
    """
    if not date_str:
        return "Không rõ ngày"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=None)
    except Exception:
        # Try YYYY-MM-DD only
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            return date_str[:10] or "Không rõ ngày"
    now = datetime.now()
    delta = now - dt
    if delta.days < 0:
        return dt.strftime("%Y-%m-%d")  # future date — show raw
    if delta.days == 0:
        return f"Hôm nay {dt.strftime('%H:%M')}"
    if delta.days == 1:
        return "Hôm qua"
    if delta.days < 30:
        return f"{delta.days} ngày trước"
    if delta.days < 365:
        return f"⚠️ {delta.days} ngày trước"
    return f"⚠️ {dt.strftime('%Y-%m-%d')} (rất cũ)"


def _pick(item: dict, *keys: str, default: str = "") -> str:
    """Return first non-empty value among the given keys."""
    for k in keys:
        v = item.get(k)
        if v and str(v).strip() not in ("", "None", "nan"):
            return str(v).strip()
    return default


def _news_card(item: dict, idx: int) -> None:
    """Render a single news card."""
    ticker   = item.get("ticker", "")
    # Support both VCI column names (news_title) and alternate naming conventions
    title    = _pick(item, "news_title", "title", "newsTitle", "headline", "name")
    subtitle = _pick(item, "news_sub_title", "sub_title", "newsSubTitle", "subtitle")
    short    = _pick(item, "news_short_content", "short_content", "description",
                     "summary", "newsShortContent") or subtitle
    full     = _pick(item, "news_full_content", "full_content", "content",
                     "newsFullContent", "body")
    link     = _normalize_news_url(
        _pick(item, "news_source_link", "source_link", "url", "link", "href")
    )
    pub_date = item.get("public_date") or item.get("created_at") or item.get("date") or ""
    age      = _fmt_age(pub_date)

    if not title:
        return

    with st.container():
        # Header row: ticker badge + age
        col_badge, col_age = st.columns([1, 5])
        with col_badge:
            st.markdown(
                f'<span style="background:#1e3a5f;color:#60a5fa;padding:2px 8px;'
                f'border-radius:4px;font-size:13px;font-weight:600">{ticker}</span>',
                unsafe_allow_html=True,
            )
        with col_age:
            st.caption(age)

        # Title
        st.markdown(f"**{title}**")

        # Short content always visible
        if short:
            st.markdown(
                f'<p style="color:#9ca3af;font-size:14px;margin:4px 0 8px 0">'
                f'{short[:300]}{"…" if len(short) > 300 else ""}</p>',
                unsafe_allow_html=True,
            )

        # Full content in expander (VCI returns this, KBS may not)
        action_cols = st.columns([2, 2, 6])
        if full and full != short:
            with action_cols[0]:
                with st.expander("📖 Đọc thêm"):
                    st.markdown(full[:3000] + ("…" if len(full) > 3000 else ""))
        if link:
            with action_cols[1]:
                st.markdown(
                    f'<a href="{link}" target="_blank" rel="noopener noreferrer">🔗 Nguồn gốc</a>',
                    unsafe_allow_html=True,
                )

        st.divider()


def render_news_tab() -> None:
    """Main entry point called from vnstock_dashboard.py."""
    try:
        import vnstock_news as _nn
    except ImportError:
        st.error("Không tìm thấy `vnstock_news.py`. Đảm bảo file tồn tại trong thư mục gốc.")
        return

    st.markdown("#### 🗞️ Tin tức thị trường")

    # ── Cache status & controls ────────────────────────────────────────────
    info = _nn.cache_info()
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([3, 2, 2])

    with ctrl_col1:
        if info["exists"] and info["count"]:
            age_txt = f"{info['age_minutes']} phút trước" if info["age_minutes"] is not None else "N/A"
            st.caption(f"📦 Cache: **{info['count']}** tin · cập nhật **{age_txt}**")
        else:
            st.caption("⚠️ Chưa có cache. Bấm **Cập nhật** để tải tin tức.")

    with ctrl_col2:
        refresh_clicked = st.button("🔄 Cập nhật tin tức", key="_news_refresh",
                                     help="Tải tin từ vnstock cho toàn bộ universe (~1-3 phút tuỳ số mã)")
    with ctrl_col3:
        top_n_universe = st.number_input(
            "Screener top-N", min_value=10, max_value=500,
            value=100, step=50, key="_news_top_n",
            help=(
                "Số mã từ screener bổ sung vào VN30. "
                "100 ≈ 1 phút · 300 ≈ 2-3 phút · 500 ≈ 4-5 phút. "
                "Screener đã có điểm số cho ~1,600 mã nên top-500 ≈ toàn thị trường liquid."
            ),
        )

    # ── Refresh ────────────────────────────────────────────────────────────
    if refresh_clicked:
        universe = _nn.build_universe(top_screener=int(top_n_universe))
        prog_bar = st.progress(0.0, text=f"Đang tải tin cho {len(universe)} mã…")
        _status  = st.empty()

        def _cb(done: int, total: int) -> None:
            pct = done / total
            prog_bar.progress(pct, text=f"Đã xử lý {done}/{total} mã…")

        with st.spinner("Đang tải tin tức…"):
            news_all = _nn.refresh_news(universe=universe, progress_cb=_cb)

        prog_bar.empty()
        _status.success(f"✅ Đã tải **{len(news_all)}** tin cho **{len(universe)}** mã!")
        st.session_state["_news_data"] = news_all

    # ── Load data ──────────────────────────────────────────────────────────
    if "_news_data" not in st.session_state:
        st.session_state["_news_data"] = _nn.load_news_cache()

    news: list[dict] = st.session_state["_news_data"]

    if not news:
        st.info("Chưa có tin tức. Bấm **🔄 Cập nhật tin tức** để tải về.")
        return

    # ── Cache freshness diagnostic ─────────────────────────────────────────
    # If even the NEWEST item in cache is days old, warn the user — the news
    # source may be stale or the date field wasn't parsed correctly.
    _dated_items = [n for n in news if n.get("_date_sort")]
    _undated_count = len(news) - len(_dated_items)
    if _dated_items:
        from datetime import date as _date
        _newest_iso = max(n["_date_sort"] for n in _dated_items)
        try:
            _newest_dt = datetime.strptime(_newest_iso[:10], "%Y-%m-%d").date()
            _age_days = (_date.today() - _newest_dt).days
            if _age_days >= 3:
                st.warning(
                    f"⚠️ Tin mới nhất trong cache là từ **{_newest_iso}** "
                    f"({_age_days} ngày trước). Nguồn tin có thể đang cũ — "
                    f"thử **Cập nhật tin tức** lại sau vài giờ."
                )
        except Exception:
            pass
    if _undated_count > 0 and _undated_count >= len(news) // 2:
        st.warning(
            f"⚠️ {_undated_count}/{len(news)} tin không có ngày phát hành "
            f"(field date không được parse). Sort theo ngày sẽ không chính xác."
        )

    # ── Filters ────────────────────────────────────────────────────────────
    st.markdown("---")
    flt_col1, flt_col2, flt_col3, flt_col4 = st.columns([2, 2, 2, 3])

    # Ticker filter
    all_tickers = sorted({n.get("ticker", "") for n in news if n.get("ticker")})
    with flt_col1:
        selected_ticker = st.selectbox(
            "Lọc mã", options=["Tất cả"] + all_tickers,
            key="_news_ticker_filter",
        )

    # Recency filter — default to 7 days so users don't see month-old news
    # by default. The "Tất cả" option is available for explicit override.
    with flt_col2:
        recency_label = st.selectbox(
            "Tin trong",
            options=["3 ngày", "7 ngày", "30 ngày", "Tất cả"],
            index=1,  # default: 7 ngày
            key="_news_recency_filter",
        )
    _recency_days = {"3 ngày": 3, "7 ngày": 7, "30 ngày": 30, "Tất cả": None}[recency_label]

    # Specific-date filter (only dates present in cache)
    all_dates = sorted({n.get("_date_sort", "")[:10] for n in news if n.get("_date_sort")}, reverse=True)
    with flt_col3:
        selected_date = st.selectbox(
            "Ngày cụ thể", options=["Tất cả"] + all_dates,
            key="_news_date_filter",
        )

    # Search
    with flt_col4:
        search_q = st.text_input("🔍 Tìm kiếm tiêu đề", key="_news_search",
                                  placeholder="VCB, tăng trưởng, lợi nhuận…")

    # Page size
    page_size = st.select_slider(
        "Số tin hiển thị mỗi trang", options=[10, 20, 50, 100], value=20,
        key="_news_page_size",
    )

    # ── Apply filters ──────────────────────────────────────────────────────
    filtered = news

    # Recency filter — drop items older than N days OR with no date
    if _recency_days is not None:
        from datetime import date as _date, timedelta as _td
        _cutoff = (_date.today() - _td(days=_recency_days)).isoformat()
        filtered = [n for n in filtered if (n.get("_date_sort") or "") >= _cutoff]

    if selected_ticker != "Tất cả":
        filtered = [n for n in filtered if n.get("ticker", "").upper() == selected_ticker.upper()]

    if selected_date != "Tất cả":
        filtered = [n for n in filtered if n.get("_date_sort", "").startswith(selected_date)]

    if search_q:
        q = search_q.lower()
        filtered = [
            n for n in filtered
            if q in _pick(n, "news_title", "title", "newsTitle", "headline").lower()
            or q in _pick(n, "news_short_content", "short_content", "description", "summary").lower()
            or q in (n.get("ticker") or "").lower()
        ]

    # ── Debug: show raw keys if nothing renders (helps diagnose column-name mismatches)
    _n_renderable = sum(
        1 for n in filtered[:page_size]
        if _pick(n, "news_title", "title", "newsTitle", "headline", "name")
    )
    if filtered and _n_renderable == 0:
        with st.expander("⚠️ Không hiển thị được tin — xem cấu trúc dữ liệu", expanded=True):
            st.warning(
                "Tất cả items đều thiếu trường tiêu đề. "
                "Hãy **Cập nhật tin tức** lại để refresh cache."
            )
            st.caption("Keys của item đầu tiên:")
            st.json(dict(list(filtered[0].items())[:20]))
        return

    st.caption(f"Hiển thị **{min(len(filtered), page_size)}** / **{len(filtered)}** tin")

    if not filtered:
        st.info("Không có tin tức phù hợp với bộ lọc.")
        return

    # ── Render cards ───────────────────────────────────────────────────────
    for i, item in enumerate(filtered[:page_size]):
        _news_card(item, i)

    if len(filtered) > page_size:
        st.caption(f"… còn {len(filtered) - page_size} tin nữa. Tăng **Số tin hiển thị** để xem thêm.")

    # ── AI context preview (collapsible) ──────────────────────────────────
    with st.expander("🤖 Xem context đang inject vào AI agents", expanded=False):
        tickers_for_ai = (
            [selected_ticker] if selected_ticker != "Tất cả" else None
        )
        ctx = _nn.news_context_block(tickers=tickers_for_ai, max_items=15)
        if ctx:
            st.code(ctx, language="markdown")
        else:
            st.caption("Chưa có tin tức nào trong cache để inject.")
