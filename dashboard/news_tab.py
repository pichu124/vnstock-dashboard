"""dashboard/news_tab.py — News tab for VNStock Dashboard.

Displays an aggregated news feed for all tracked market tickers.
News is fetched via vnstock (VCI → KBS fallback), cached to disk,
and made available to AI agents in brief & analysis contexts.
"""

from __future__ import annotations

import streamlit as st
from datetime import datetime, date, timedelta, timezone
import importlib
import inspect
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


_VN_TZ = timezone(timedelta(hours=7))


def _fmt_age(date_str: str, now: datetime | None = None) -> str:
    """Human-readable age: 'Hôm nay 14:30', '2 ngày trước'.

    Đếm theo NGÀY LỊCH giờ VN — khớp bộ lọc "Hôm nay" (so `_vn_day`);
    timedelta.days từng gọi tin 20:00 hôm qua là "Hôm nay" lúc 08:00.

    Returns 'Không rõ ngày' for unparseable input so the user can spot
    items with missing date metadata (instead of silent empty caption).
    """
    if not date_str:
        return "Không rõ ngày"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is not None:          # "…Z" = UTC → quy về giờ VN
            dt = dt.astimezone(_VN_TZ).replace(tzinfo=None)
    except Exception:
        # Try YYYY-MM-DD only
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            return date_str[:10] or "Không rõ ngày"
    days = ((now or datetime.now()).date() - dt.date()).days
    if days < 0:
        return dt.strftime("%Y-%m-%d")  # future date — show raw
    if days == 0:
        return f"Hôm nay {dt.strftime('%H:%M')}"
    if days == 1:
        return "Hôm qua"
    if days < 30:
        return f"{days} ngày trước"
    if days < 365:
        return f"⚠️ {days} ngày trước"
    return f"⚠️ {dt.strftime('%Y-%m-%d')} (rất cũ)"


def _pub_raw(item: dict) -> str:
    """Timestamp gốc mà thẻ tin hiển thị tuổi."""
    return item.get("public_date") or item.get("created_at") or item.get("date") or ""


def _vn_day(item: dict) -> str:
    """Ngày lịch giờ VN 'YYYY-MM-DD' cho bộ lọc ngày — cùng cách `_fmt_age` gắn nhãn.

    `_date_sort` là ngày UTC khi nguồn ghi "…Z", nhưng nó là khoá dedup / hash
    sentiment / sổ đã gửi nên không đổi ⇒ chỉ quy lại ở đây, cho tin có tz.
    """
    try:
        dt = datetime.fromisoformat(str(_pub_raw(item)).replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(_VN_TZ).date().isoformat()
    return (item.get("_date_sort") or "")[:10]


def _pick(item: dict, *keys: str, default: str = "") -> str:
    """Return first non-empty value among the given keys."""
    for k in keys:
        v = item.get(k)
        if v and str(v).strip() not in ("", "None", "nan"):
            return str(v).strip()
    return default


_SENTIMENT_BADGE = {
    "positive": '<span style="background:#14532d;color:#86efac;padding:1px 7px;border-radius:4px;font-size:12px">🟢 Tích cực</span>',
    "negative": '<span style="background:#450a0a;color:#fca5a5;padding:1px 7px;border-radius:4px;font-size:12px">🔴 Tiêu cực</span>',
    "neutral":  '<span style="background:#1c1917;color:#a8a29e;padding:1px 7px;border-radius:4px;font-size:12px">⚪ Trung lập</span>',
}


def _news_card(item: dict, idx: int) -> None:
    """Render a single news card."""
    ticker    = item.get("ticker", "")
    # Support both VCI column names (news_title) and alternate naming conventions
    title     = _pick(item, "news_title", "title", "newsTitle", "headline", "name")
    subtitle  = _pick(item, "news_sub_title", "sub_title", "newsSubTitle", "subtitle")
    short     = _pick(item, "news_short_content", "short_content", "description",
                      "summary", "newsShortContent") or subtitle
    full      = _pick(item, "news_full_content", "full_content", "content",
                      "newsFullContent", "body")
    link      = _normalize_news_url(
        _pick(item, "news_source_link", "source_link", "url", "link", "href")
    )
    pub_date  = _pub_raw(item)
    age       = _fmt_age(pub_date)
    sentiment = item.get("_sentiment", "")

    if not title:
        return

    with st.container():
        # Header row: ticker badge + sentiment badge + age
        col_badge, col_sent, col_age = st.columns([1, 1, 4])
        with col_badge:
            st.markdown(
                f'<span style="background:#1e3a5f;color:#60a5fa;padding:2px 8px;'
                f'border-radius:4px;font-size:13px;font-weight:600">{ticker}</span>',
                unsafe_allow_html=True,
            )
        with col_sent:
            if sentiment in _SENTIMENT_BADGE:
                st.markdown(_SENTIMENT_BADGE[sentiment], unsafe_allow_html=True)
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


def lazy_tabs(st, labels: list[str], key: str):
    """`st.tabs` chỉ chạy tab đang mở nếu streamlit có `on_change` (1.56 có): đổi tab ⇒ rerun,
    `.open` báo tab nào mở. Bản cũ (requirements ghim >=1.35) ⇒ như trước, chạy hết.
    Widget trong tab ẩn bị dọn state khi rời tab — như nav chính `st.pills`."""
    if "on_change" in inspect.signature(st.tabs).parameters:
        return st.tabs(labels, key=key, on_change="rerun")
    return st.tabs(labels)


def tab_open(tab) -> bool:
    """False chỉ khi tabs có trạng thái và tab này đang ẩn (bản cũ: không có `.open`/None)."""
    return getattr(tab, "open", None) is not False


_SUBTABS = (  # (nhãn, module, hàm) — module None = tin theo mã ngay trong file này
    ("📰 Tin theo mã", None, None),
    ("🌐 Vĩ mô", "dashboard.macro_tab", "render_macro_subtab"),
    ("📄 Báo cáo tuần", "dashboard.rates_report_tab", "render_rates_report_subtab"),
    ("📚 Báo cáo", "dashboard.reports_tab", "render_reports_subtab"),
    ("🧭 Phân bổ", "dashboard.allocation_tab", "render_allocation_subtab"),
)


def render_news_tab() -> None:
    """Main entry point called from vnstock_dashboard.py.

    5 sub-tab: tin THEO MÃ (nội dung gốc của tab), 🌐 Vĩ mô (macro_tab —
    thuần hiển thị), 📄 Báo cáo tuần (rates_report_tab — HTML lãi suất từ
    cache), 📚 Báo cáo (reports_tab — ingest + digest, P5) và 🧭 Phân bổ
    (allocation_tab — band B0-B4 + scorecard, P5).
    """
    tabs = lazy_tabs(st, [label for label, _, _ in _SUBTABS], key="_news_subtab")
    for tab, (label, mod, fn) in zip(tabs, _SUBTABS):
        if not tab_open(tab):
            continue
        with tab:
            if mod is None:
                _render_ticker_news()
                continue
            try:
                getattr(importlib.import_module(mod), fn)()
            except Exception as _e:                          # noqa
                st.error(f"Không render được sub-tab {label.split(' ', 1)[1]}: {_e}")


@st.cache_data(show_spinner=False, max_entries=4)
def _cache_info(stamp: tuple) -> dict:
    """`cache_info` parse cả news_cache.json (~1 MB, ~16 ms đo 17/10) chỉ để đếm ⇒ đệm tới khi
    file đổi (`stamp` = đường dẫn + mtime)."""
    import vnstock_news as _nn
    return _nn.cache_info()


def _render_ticker_news() -> None:
    """Tin tức theo mã (vnstock_news) — nguyên trạng nội dung tab cũ."""
    try:
        import vnstock_news as _nn
    except ImportError:
        st.error("Không tìm thấy `vnstock_news.py`. Đảm bảo file tồn tại trong thư mục gốc.")
        return

    try:
        import vnstock_sentiment as _snt
        _sentiment_available = True
    except ImportError:
        _sentiment_available = False

    st.markdown("#### 🗞️ Tin tức thị trường")

    # ── Cache status & controls ────────────────────────────────────────────
    _p = _nn.NEWS_CACHE_PATH
    info = _cache_info((str(_p), _p.stat().st_mtime_ns if _p.exists() else None))
    if info.get("fetched_at"):        # tuổi tính lại mỗi lượt, không lấy bản đệm
        info["age_minutes"] = round(
            (datetime.now() - datetime.fromisoformat(info["fetched_at"])).total_seconds() / 60, 1)
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([3, 2, 2, 2])

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
        # Quick refresh + auto-set filter to "Hôm nay" so the user sees only
        # today's news immediately after fetch completes.
        today_clicked = st.button("📅 Tải tin hôm nay", key="_news_refresh_today",
                                   help="Tải tin và lọc về tin trong hôm nay")
    with ctrl_col4:
        top_n_universe = st.number_input(
            "Screener top-N", min_value=10, max_value=500,
            value=100, step=50, key="_news_top_n",
            help=(
                "Số mã từ screener bổ sung vào VN30. "
                "100 ≈ 1 phút · 300 ≈ 2-3 phút · 500 ≈ 4-5 phút."
            ),
        )

    # ── Dedup existing cache ───────────────────────────────────────────────
    dedup_col1, dedup_col2 = st.columns([2, 8])
    with dedup_col1:
        dedup_clicked = st.button(
            "🧹 Dedup cache",
            key="_news_dedup",
            help="Xoá các tin trùng/gần trùng (cùng ngày + title similarity ≥ 85%). Tin mới refresh đã tự dedup.",
        )
    if dedup_clicked:
        _existing = _nn.load_news_cache()
        _deduped, _n_removed = _nn.deduplicate_news(_existing)
        if _n_removed > 0:
            _nn.save_news_cache(_deduped)
            st.session_state["_news_data"] = _deduped
            with dedup_col2:
                st.success(f"✅ Đã xoá **{_n_removed}** tin trùng. Còn {len(_deduped)} tin.")
        else:
            with dedup_col2:
                st.info("Không có tin trùng. Cache đã sạch.")

    # ── Sentiment controls ─────────────────────────────────────────────────
    if _sentiment_available:
        snt_col1, snt_col2 = st.columns([2, 8])
        with snt_col1:
            score_clicked = st.button(
                "🧠 Phân tích sentiment",
                key="_news_score_sentiment",
                help="Dùng AI (Groq/Cerebras/OpenRouter) để phân loại tin tức tích cực/tiêu cực. Mỗi tin chỉ gọi API 1 lần.",
            )
        with snt_col2:
            provider_name = _snt.available_provider()
            if not provider_name:
                st.caption("⚠️ Chưa có API key cho Groq/Cerebras/OpenRouter — sentiment không khả dụng.")
    else:
        score_clicked = False

    # ── Refresh ────────────────────────────────────────────────────────────
    if today_clicked:
        # Set filter pref before refresh so the post-fetch render uses it.
        st.session_state["_news_recency_filter"] = "Hôm nay"
        refresh_clicked = True

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
        if news_all:
            _status.success(f"✅ Đã tải **{len(news_all)}** tin cho **{len(universe)}** mã!")
        else:
            _status.error(
                f"❌ Không tải được tin nào cho **{len(universe)}** mã — nguồn tin "
                "(VCI/KBS) lỗi, mạng hỏng, hoặc nguồn chưa có tin. Thử lại sau.")
        # Lượt hỏng không ghi đè cache (refresh_news) ⇒ vẫn hiện tin cũ.
        st.session_state["_news_data"] = news_all or _nn.load_news_cache()
        # Reset recency filter after refresh — "Hôm nay" from today_clicked
        # would show 0 results if the news source doesn't publish today yet.
        if st.session_state.get("_news_recency_filter") == "Hôm nay":
            _newest = max(map(_vn_day, news_all)) if news_all else ""
            if _newest < date.today().isoformat():
                st.session_state["_news_recency_filter"] = "7 ngày"

    # ── Load data ──────────────────────────────────────────────────────────
    if "_news_data" not in st.session_state:
        st.session_state["_news_data"] = _nn.load_news_cache()
    else:
        # Rehydrate _date_sort in-place if any items are missing it (e.g.
        # session_state was populated before the field-detection fix).
        _missing = sum(1 for n in st.session_state["_news_data"]
                       if not n.get("_date_sort"))
        if _missing > 0 and hasattr(_nn, "_rehydrate_date_sort"):
            fixed = _nn._rehydrate_date_sort(st.session_state["_news_data"])
            if fixed > 0:
                st.session_state["_news_data"].sort(
                    key=lambda x: x.get("_date_sort") or "0000-00-00",
                    reverse=True,
                )

    news: list[dict] = st.session_state["_news_data"]

    if not news:
        st.info("Chưa có tin tức. Bấm **🔄 Cập nhật tin tức** để tải về.")
        return

    # ── Sentiment scoring ──────────────────────────────────────────────────
    if _sentiment_available:
        # Always attach cached sentiments (fast, no LLM call)
        _snt.attach_sentiments(news)

        if score_clicked:
            already = _snt.scored_count(news)
            to_score_n = len(news) - already
            if to_score_n == 0:
                st.success(f"✅ Tất cả {len(news)} tin đã được chấm sentiment.")
            else:
                _snt_prog = st.progress(0.0, text=f"Đang phân tích sentiment cho {to_score_n} tin…")
                _snt_status = st.empty()

                def _snt_cb(done: int, total: int) -> None:
                    if total > 0:
                        _snt_prog.progress(done / total, text=f"Sentiment: {done}/{total}…")

                with st.spinner("Đang phân tích sentiment…"):
                    # allow_cli=False: không spawn Claude Code trong Streamlit
                    # (đứng 300s/lô) — engine claude chỉ ở pipeline đêm.
                    _snt.score_news_batch(news, progress_cb=_snt_cb, allow_cli=False)
                _snt.attach_sentiments(news)
                _snt_prog.empty()
                _scored_now = _snt.scored_count(news)
                _snt_status.success(f"✅ Đã chấm sentiment cho **{_scored_now}/{len(news)}** tin!")
                st.rerun()

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
        # Self-diagnose: dump first item's keys so we can identify the actual
        # date field name used by the provider. Without this the user has no
        # way to know which field to add to vnstock_news._DATE_FIELDS.
        with st.expander("🔬 Debug: cấu trúc dữ liệu thô (giúp xác định field date)", expanded=True):
            sample = news[0] if news else {}
            st.caption(f"Tổng số keys: {len(sample)}")
            # Highlight keys that LOOK date-related
            date_like = {k: v for k, v in sample.items()
                         if any(s in k.lower() for s in ("date", "time", "publish", "create"))}
            if date_like:
                st.caption("**Keys có vẻ là date** (substring date/time/publish/create):")
                st.json(date_like)
            else:
                st.caption("⚠️ Không có key nào chứa substring date/time/publish/create.")
            st.caption("**Toàn bộ keys:**")
            st.json({k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v)
                     for k, v in list(sample.items())[:30]})
            st.caption(
                "→ Copy tên field date thực và báo lại để thêm vào "
                "`vnstock_news._DATE_FIELDS`."
            )

    # ── Filters ────────────────────────────────────────────────────────────
    st.markdown("---")

    # Coverage diagnostic: show distribution of articles by date + by ticker
    # so the user can see at a glance how sparse / dense the cache is. This
    # answers the common confusion of "why so few recent news" — usually
    # vnstock's company.news() returns only ~1 latest article per ticker
    # so coverage of recent news depends entirely on which tickers happened
    # to have publications in the window.
    with st.expander("📊 Phân bố tin trong cache (chẩn đoán)", expanded=False):
        from collections import Counter
        date_counter = Counter(
            (n.get("_date_sort") or "Không rõ ngày")[:10] for n in news
        )
        ticker_counter = Counter(n.get("ticker", "?") for n in news)
        n_tickers_with_news = len([t for t in ticker_counter if t and t != "?"])
        avg_per_ticker = len(news) / max(n_tickers_with_news, 1)

        m1, m2, m3 = st.columns(3)
        m1.metric("Tổng tin", len(news))
        m2.metric("Số mã có tin", n_tickers_with_news)
        m3.metric("TB tin/mã", f"{avg_per_ticker:.1f}")

        diag_col1, diag_col2 = st.columns(2)
        with diag_col1:
            st.caption("**Phân bố theo ngày** (sắp xếp mới nhất trên đầu)")
            import pandas as _pd
            df_d = _pd.DataFrame([
                {"Ngày": d, "Số tin": c}
                for d, c in sorted(date_counter.items(), reverse=True)
            ])
            st.dataframe(df_d, hide_index=True, height=240, use_container_width=True)
        with diag_col2:
            st.caption("**Top 30 mã nhiều tin nhất**")
            df_t = _pd.DataFrame([
                {"Mã": t, "Số tin": c}
                for t, c in ticker_counter.most_common(30)
            ])
            st.dataframe(df_t, hide_index=True, height=240, use_container_width=True)
        st.caption(
            "💡 Nếu TB tin/mã thấp (~1) và phân bố ngày tản mác, là do "
            "`vnstock.company.news()` chỉ trả ~1 tin gần nhất mỗi mã. "
            "Mã chưa có tin trong khung thời gian sẽ trả về tin cũ. "
            "Tăng **Screener top-N** để thêm nhiều mã active hơn vào universe."
        )

        # Live API diagnostic: fetch one ticker and show what each code path
        # returns. Helps determine whether vnstock_data.Company.news() is
        # actually returning more articles than vnstock free.
        st.markdown("---")
        st.caption("**Test fetch live cho 1 mã** (kiểm tra API trả gì)")
        diag_col_a, diag_col_b = st.columns([1, 5])
        with diag_col_a:
            diag_ticker = st.text_input("Mã", value="VCB", key="_news_diag_ticker",
                                          max_chars=5)
        with diag_col_b:
            if st.button("🧪 Test fetch", key="_news_diag_run"):
                if hasattr(_nn, "diagnose_news_fetch"):
                    with st.spinner(f"Đang fetch {diag_ticker}…"):
                        result = _nn.diagnose_news_fetch(diag_ticker.strip().upper())
                    st.json(result)
                else:
                    st.warning("diagnose_news_fetch chưa có — pull bản mới nhất")

    flt_col1, flt_col2, flt_col3, flt_col4 = st.columns([2, 2, 2, 3])

    # Ticker filter
    all_tickers = sorted({n.get("ticker", "") for n in news if n.get("ticker")})
    with flt_col1:
        selected_ticker = st.selectbox(
            "Lọc mã", options=["Tất cả"] + all_tickers,
            key="_news_ticker_filter",
        )

    # Recency filter — default to 7 days so users don't see month-old news
    # by default. "Hôm nay" filters to today only; "Tất cả" disables filter.
    with flt_col2:
        recency_label = st.selectbox(
            "Tin trong",
            options=["Hôm nay", "3 ngày", "7 ngày", "30 ngày", "Tất cả"],
            index=2,  # default: 7 ngày
            key="_news_recency_filter",
        )
    _recency_days = {
        "Hôm nay": 0, "3 ngày": 3, "7 ngày": 7, "30 ngày": 30, "Tất cả": None
    }[recency_label]

    # Specific-date filter (only dates present in cache)
    all_dates = sorted({d for d in map(_vn_day, news) if d}, reverse=True)
    with flt_col3:
        selected_date = st.selectbox(
            "Ngày cụ thể", options=["Tất cả"] + all_dates,
            key="_news_date_filter",
        )

    # Search
    with flt_col4:
        search_q = st.text_input("🔍 Tìm kiếm tiêu đề", key="_news_search",
                                  placeholder="VCB, tăng trưởng, lợi nhuận…")

    # Sentiment filter (only shown when some items are scored)
    _any_scored = _sentiment_available and any(n.get("_sentiment") for n in news)
    snt_filter_col, page_col = st.columns([2, 3])
    with snt_filter_col:
        if _any_scored:
            sentiment_filter = st.selectbox(
                "Sentiment",
                options=["Tất cả", "🟢 Tích cực", "🔴 Tiêu cực", "⚪ Trung lập"],
                key="_news_sentiment_filter",
            )
        else:
            sentiment_filter = "Tất cả"
    with page_col:
        page_size = st.select_slider(
            "Số tin hiển thị mỗi trang", options=[10, 20, 50, 100], value=20,
            key="_news_page_size",
        )

    # ── Apply filters ──────────────────────────────────────────────────────
    filtered = news

    # Recency filter — drop items older than N days OR with no date
    if _recency_days is not None:
        _cutoff = (date.today() - timedelta(days=_recency_days)).isoformat()
        filtered = [n for n in filtered if _vn_day(n) >= _cutoff]

    if selected_ticker != "Tất cả":
        filtered = [n for n in filtered if n.get("ticker", "").upper() == selected_ticker.upper()]

    if selected_date != "Tất cả":
        filtered = [n for n in filtered if _vn_day(n) == selected_date]

    if search_q:
        q = search_q.lower()
        filtered = [
            n for n in filtered
            if q in _pick(n, "news_title", "title", "newsTitle", "headline").lower()
            or q in _pick(n, "news_short_content", "short_content", "description", "summary").lower()
            or q in (n.get("ticker") or "").lower()
        ]

    _snt_map = {
        "🟢 Tích cực": "positive",
        "🔴 Tiêu cực": "negative",
        "⚪ Trung lập": "neutral",
    }
    if sentiment_filter in _snt_map:
        filtered = [n for n in filtered if n.get("_sentiment") == _snt_map[sentiment_filter]]

    # ── Sentiment summary ──────────────────────────────────────────────────
    if _sentiment_available:
        _scored_items = [n for n in news if n.get("_sentiment")]
        if _scored_items:
            # Aggregate window is independent of the news recency filter —
            # always show full 30-day picture so the table is never empty
            # just because the user filtered news to "Hôm nay".
            _agg_days = 30

            with st.expander(
                f"📊 Tổng kết sentiment theo mã (30 ngày, {len(_scored_items)} tin đã chấm)",
                expanded=len(_scored_items) > 0,
            ):
                import pandas as _pd

                summary = _snt.ticker_sentiment_summary(news, days=_agg_days)
                if summary:
                    df_snt = _pd.DataFrame(summary)
                    st.dataframe(df_snt, hide_index=True, use_container_width=True)
                else:
                    st.caption("Chưa có dữ liệu sentiment trong 30 ngày gần đây.")

                # Timeline chart for selected ticker
                if selected_ticker != "Tất cả":
                    timeline = _snt.sentiment_timeline(selected_ticker, news, days=_agg_days)
                    if len(timeline) >= 2:
                        st.markdown(f"**Sentiment timeline — {selected_ticker}**")
                        try:
                            import plotly.graph_objects as go
                            dates = [r["date"] for r in timeline]
                            fig = go.Figure()
                            fig.add_bar(
                                x=dates, y=[r["positive"] for r in timeline],
                                name="Tích cực", marker_color="#22c55e",
                            )
                            fig.add_bar(
                                x=dates, y=[-r["negative"] for r in timeline],
                                name="Tiêu cực", marker_color="#ef4444",
                            )
                            fig.add_bar(
                                x=dates, y=[r["neutral"] for r in timeline],
                                name="Trung lập", marker_color="#6b7280",
                            )
                            fig.update_layout(
                                barmode="relative",
                                height=220,
                                margin=dict(l=0, r=0, t=0, b=0),
                                paper_bgcolor="rgba(0,0,0,0)",
                                plot_bgcolor="rgba(0,0,0,0)",
                                font_color="#e5e7eb",
                                legend=dict(orientation="h", y=1.1),
                                xaxis=dict(showgrid=False),
                                yaxis=dict(title="# tin", showgrid=True, gridcolor="#374151"),
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        except ImportError:
                            st.caption("Cài `plotly` để xem sentiment timeline chart.")
                    elif timeline:
                        st.caption(f"Chỉ có {len(timeline)} ngày data — cần ≥2 để vẽ chart.")
        else:
            st.caption("💡 Bấm **🧠 Phân tích sentiment** để chấm điểm tin tức.")

    st.caption(f"Hiển thị **{min(len(filtered), page_size)}** / **{len(filtered)}** tin")

    if not filtered:
        if _recency_days == 0 and all_dates:
            _latest = all_dates[0]
            st.info(
                f"Không có tin từ hôm nay ({date.today().isoformat()}). "
                f"Tin mới nhất trong cache là từ **{_latest}**. "
                f"Đổi bộ lọc sang **7 ngày** hoặc bấm 🔄 để cập nhật."
            )
        else:
            st.info("Không có tin tức phù hợp với bộ lọc.")
        return

    # ── Debug: show raw keys if nothing renders (helps diagnose column-name mismatches)
    _n_renderable = sum(
        1 for n in filtered[:page_size]
        if _pick(n, "news_title", "title", "newsTitle", "headline", "name")
    )
    if _n_renderable == 0:
        with st.expander("⚠️ Không hiển thị được tin — xem cấu trúc dữ liệu", expanded=True):
            st.warning(
                "Tất cả items đều thiếu trường tiêu đề. "
                "Hãy **Cập nhật tin tức** lại để refresh cache."
            )
            st.caption("Keys của item đầu tiên:")
            st.json(dict(list(filtered[0].items())[:20]))
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
