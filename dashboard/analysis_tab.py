"""
Phân tích tab — 🔬 per-ticker technical/fundamental deep-dive.

The largest and most stateful tab: ticker selector, chart options,
timeframe switcher, live-mode toggle, fundamental panel, volume profile,
order book, and alert wiring. Extracted last per the modularisation
plan (docs/REFACTOR_PLAN.md) since it has the heaviest dependency
surface.

Extraction notes
----------------
Streamlit is imported lazily so the module is pytest-importable
without the runtime. Every dashboard-level helper the block uses
(roughly thirty symbols — price/fundamental loaders, live-quote
merging, chart/indicator renderers, alert firing, WSS singleton) is
lazy-imported from ``vnstock_dashboard`` inside the render function.
This avoids circular-import pain because dispatch only fires after
the dashboard module has finished initialising.
"""

from __future__ import annotations


def render_analysis_tab() -> None:
    """Render the Phân tích tab. Lazy imports Streamlit + dashboard helpers."""
    try:
        import streamlit as st
    except ImportError:
        print("[analysis_tab] streamlit not available")
        return

    import sys
    import json
    import numpy as np
    import pandas as pd
    from datetime import datetime, timedelta, time as _time
    from pathlib import Path

    if 'vnstock_dashboard' not in sys.modules:
        _m = sys.modules.get('__main__') or sys.modules.get('main')
        if _m and hasattr(_m, 'WSS_AVAILABLE'):
            sys.modules['vnstock_dashboard'] = _m

    from vnstock_dashboard import (
        WSS_AVAILABLE,
        _get_wss_singleton, _merge_live_quote, _normalize_live_price,
        check_and_fire_alerts, fetch_volume_profile_direct, fmt_pct,
        get_all_listed_symbols, get_all_tickers, get_tech_signals,
        is_futures,
        list_available_bar_dates, list_live_futures,
        load_alerts, load_fundamental, load_industry_map,
        load_intraday, load_intraday_bars, load_live_quote,
        load_price_history,
        render_chart, render_metric_row, render_order_book,
        render_signal_badge, render_volume_profile,
        resample_ohlcv, save_alerts,
        data,
    )
    try:
        from vnstock_dashboard import FUTURES_SYMBOLS, INDEX_SYMBOLS
    except ImportError:
        FUTURES_SYMBOLS = ["VN30F1M", "VN30F2M"]
        INDEX_SYMBOLS = ["VNINDEX", "VN30", "HNX30"]

    # Controls cho tab phân tích
    with st.sidebar:
        st.markdown("### 🔬 Phân tích")

        # Ticker autocomplete — selectbox với mã + tên công ty
        _ind_map = load_industry_map()
        _all_tickers_list = get_all_tickers()
        if WSS_AVAILABLE:
            # Merge thêm mã từ full market list
            _wss_syms = get_all_listed_symbols()
            _all_set = set(_all_tickers_list) | set(_wss_syms)
            _all_tickers_list = sorted(_all_set)

        _ticker_options = [""]
        _ticker_labels = {"": "— Nhập hoặc chọn mã —"}
        for _t in _all_tickers_list:
            _name = _ind_map.get(_t, {}).get("company_name", "")
            _ind = _ind_map.get(_t, {}).get("industry", "")
            _label = f"{_t} — {_name}" if _name else _t
            if _ind:
                _label += f" ({_ind[:20]})"
            _ticker_options.append(_t)
            _ticker_labels[_t] = _label

        # Thêm futures
        for _ft in FUTURES_SYMBOLS:
            if _ft not in _ticker_labels:
                _ticker_options.append(_ft)
                _ticker_labels[_ft] = f"{_ft} — Hợp đồng tương lai VN30"
        # Thêm index
        for _ix in INDEX_SYMBOLS:
            if _ix not in _ticker_labels:
                _ticker_options.append(_ix)
                _ticker_labels[_ix] = f"{_ix} — Chỉ số"

        ticker_input = st.selectbox(
            "Mã cổ phiếu",
            options=_ticker_options,
            format_func=lambda x: _ticker_labels.get(x, x),
            key="ticker_sidebar",
            placeholder="Tìm mã...",
        )
        if ticker_input:
            ticker_input = ticker_input.upper().strip()
            st.session_state["analyze_ticker"] = ticker_input

        # Futures quick picker — nếu WSS đang chạy và có live futures
        if WSS_AVAILABLE:
            _live_futs = list_live_futures()
            if _live_futs:
                _fut_pick = st.selectbox(
                    "📑 Hợp đồng tương lai",
                    ["— chọn —"] + _live_futs,
                    key="futures_picker",
                    help="Danh sách futures đang có live data (10 mức order book)"
                )
                if _fut_pick and _fut_pick != "— chọn —":
                    if st.button(f"Phân tích {_fut_pick} →",
                                 use_container_width=True, key="anal_fut_go"):
                        st.session_state["analyze_ticker"] = _fut_pick

        st.divider()
        st.markdown("### ⏱ Khoảng thời gian")
        lookback = st.select_slider(
            "Lọc từ",
            options=[0, 365, 730, 1825, 3650],
            value=0,
            format_func=lambda v: {0:"Toàn bộ lịch sử",365:"1 năm",730:"2 năm",1825:"5 năm",3650:"10 năm"}[v],
            key="lookback_anal"
        )
        load_fund = st.toggle("Tải dữ liệu cơ bản (API)", value=False, key="load_fund_anal",
                              help="Gọi vnstock API để lấy P/E, ROE, EPS...")
        st.divider()
        st.markdown("### 📐 Hiển thị chart")
        chart_height = st.slider("Chiều cao chart (px)", 500, 1400, 850, step=50, key="chart_height_anal")

        # Toggle 🔴 Live Mode đã CHUYỂN LÊN sidebar chung (vnstock_dashboard,
        # cuối khối `with st.sidebar:`) — 17/08: widget nằm trong tab là bị
        # Streamlit dọn state khi user rời tab, và user còn nhầm nó với các
        # toggle "Live Scan" của Screener/Dòng Tiền. Đặt ở sidebar chung thì
        # widget render MỌI lượt (hết lớp bug dọn state) và thấy được từ mọi
        # tab. Tab này chỉ còn ĐỌC cờ `st.session_state["live_mode"]`.

        st.divider()
        st.markdown("### 📼 Intraday Replay")
        _bar_dates = list_available_bar_dates()
        if _bar_dates:
            replay_date = st.selectbox(
                "Xem lại phiên",
                options=["(tắt)"] + _bar_dates,
                index=0,
                key="replay_date",
                help="Chọn ngày để xem lại chart intraday 1m từ bars parquet"
            )
        else:
            replay_date = "(tắt)"
            st.caption("Chưa có bars parquet — bật Live Mode trong phiên để tạo")

        st.divider()
        st.markdown("### 🔔 Price Alerts")

        _alerts = load_alerts()
        _active_alerts = [a for a in _alerts if not a.get("fired")]
        _fired_alerts = [a for a in _alerts if a.get("fired")]

        st.caption(f"{len(_active_alerts)} active · {len(_fired_alerts)} fired")

        # Telegram config
        _tg_token = st.text_input("Telegram Bot Token", type="password",
                                   key="tg_token",
                                   value=st.session_state.get("_tg_token", ""))
        _tg_chat = st.text_input("Telegram Chat ID", key="tg_chat",
                                  value=st.session_state.get("_tg_chat", ""))
        if _tg_token:
            st.session_state["_tg_token"] = _tg_token
        if _tg_chat:
            st.session_state["_tg_chat"] = _tg_chat

        # Add alert
        with st.expander("➕ Thêm alert", expanded=False):
            _al_ticker = st.text_input("Mã", placeholder="VCB",
                                        key="alert_ticker").upper().strip()
            _al_cond = st.selectbox("Điều kiện", [
                "above", "below", "change_up", "change_down", "volume_above"
            ], format_func=lambda x: {
                "above": "Giá >= (mục tiêu)",
                "below": "Giá <= (mục tiêu)",
                "change_up": "Tăng >= % (trong ngày)",
                "change_down": "Giảm >= % (trong ngày)",
                "volume_above": "Volume >= (mục tiêu)",
            }.get(x, x), key="alert_cond")
            _al_target = st.number_input(
                "Giá trị mục tiêu",
                min_value=0.0, value=0.0, step=0.1,
                key="alert_target",
                help="Giá (VND) cho above/below, % cho change, số cổ phiếu cho volume"
            )
            if st.button("✅ Tạo alert", key="alert_create", use_container_width=True):
                if _al_ticker and _al_target > 0:
                    _alerts.append({
                        "ticker": _al_ticker,
                        "condition": _al_cond,
                        "target": _al_target,
                        "fired": False,
                        "created_at": __import__("datetime").datetime.now().isoformat(
                            timespec="seconds"),
                    })
                    save_alerts(_alerts)
                    st.rerun()

        # List active alerts
        if _active_alerts:
            _cond_labels = {
                "above": ">=", "below": "<=",
                "change_up": "↑%>=", "change_down": "↓%>=",
                "volume_above": "Vol>=",
            }
            for i, a in enumerate(_active_alerts):
                _lbl = _cond_labels.get(a["condition"], "?")
                st.markdown(
                    f"<span style='color:#60a5fa;font-weight:600'>{a['ticker']}</span> "
                    f"<span style='color:#9ca3af;font-size:11px'>"
                    f"{_lbl} {a['target']:,.1f}</span>",
                    unsafe_allow_html=True,
                )

        # Clear fired alerts
        if _fired_alerts:
            if st.button(f"🗑 Xoá {len(_fired_alerts)} alerts đã triggered",
                         key="alert_clear", use_container_width=True):
                save_alerts(_active_alerts)
                st.rerun()

    # ── Xác định ticker cần phân tích ─────────────────────────────────────────────
    ticker = ticker_input or st.session_state.get("analyze_ticker", "")

    if not ticker:
        # Landing page
        st.markdown("## 🔬 VnStock Analysis Dashboard")
        st.markdown('<p style="color:#6b7280">Nhập mã cổ phiếu ở sidebar để bắt đầu phân tích.</p>', unsafe_allow_html=True)

        # Hiện top movers nếu có screener data
        if data and data.get("presets"):
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**⚡ Momentum mạnh nhất**")
                mom = data["presets"].get("momentum", {}).get("results", [])[:5]
                for r in mom:
                    chg = r.get("chg_20d_pct", "")
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'padding:5px 0;border-bottom:1px solid #1a2234;cursor:pointer">'
                        f'<span style="color:#60a5fa;font-weight:600">{r["ticker"]}</span>'
                        f'<span style="color:#10b981">{chg}</span></div>',
                        unsafe_allow_html=True
                    )
            with col2:
                st.markdown("**🟢 Oversold tiềm năng**")
                ov = data["presets"].get("oversold", {}).get("results", [])[:5]
                for r in ov:
                    rsi = r.get("rsi_14", "")
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'padding:5px 0;border-bottom:1px solid #1a2234">'
                        f'<span style="color:#60a5fa;font-weight:600">{r["ticker"]}</span>'
                        f'<span style="color:#fbbf24">RSI {rsi}</span></div>',
                        unsafe_allow_html=True
                    )
        st.stop()


    # ── Load data ─────────────────────────────────────────────────────────────────
    industry_map = load_industry_map()
    company_info = industry_map.get(ticker, {})

    with st.spinner(f"Đang tải dữ liệu {ticker}..."):
        df = load_price_history(ticker, days=lookback)

    if df.empty:
        st.error(f"❌ Không tìm thấy dữ liệu giá cho mã **{ticker}**. Kiểm tra lại tên mã hoặc warehouse.")
        st.stop()

    tech = get_tech_signals(df)


    # ── Header ────────────────────────────────────────────────────────────────────
    company_name = company_info.get("company_name", ticker)
    industry     = company_info.get("industry", "")
    summary      = company_info.get("business_summary", "")

    col_h1, col_h2 = st.columns([5, 1])
    with col_h1:
        st.markdown(f"## {ticker} — {company_name}")
        if industry:
            st.markdown(
                f'<span class="tag" style="background:#1e3a5f;color:#60a5fa">{industry}</span>',
                unsafe_allow_html=True
            )
        if summary and summary not in ("", "nan", "None"):
            st.caption(summary[:200] + ("..." if len(summary) > 200 else ""))
    with col_h2:
        if st.button("🔄", help="Xóa cache và tải lại", key="anal_reload"):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")

    # ── Price metrics row ─────────────────────────────────────────────────────────
    price = tech.get("price", 0)
    render_metric_row([
        ("Giá hiện tại",  f"{price:,.1f}",              "nghìn đồng"),
        ("1 ngày",        fmt_pct(tech.get("chg1d")),   f"{df['time'].iloc[-1].strftime('%d/%m/%Y')}"),
        ("5 ngày",        fmt_pct(tech.get("chg5d")),   "so với 5 phiên trước"),
        ("20 ngày",       fmt_pct(tech.get("chg20d")),  "so với 20 phiên trước"),
        ("52W Range",     f"{tech.get('pct52', 0):.0f}%", f"Low {tech.get('lo52',0):,.1f} — High {tech.get('hi52',0):,.1f}"),
    ])

    # ── Chart ─────────────────────────────────────────────────────────────────────
    # ── Timeframe selector ──────────────────────────────────────────────
    tf_options = ["1m","5m","15m","30m","1H","1D","1W","1M","All"]
    if "tf" not in st.session_state:
        st.session_state["tf"] = "1D"
    tf_cols = st.columns(len(tf_options) + 2)
    for _i, _val in enumerate(tf_options):
        with tf_cols[_i]:
            _active = st.session_state["tf"] == _val
            if st.button(_val, key=f"tf_{_val}",
                         type="primary" if _active else "secondary",
                         use_container_width=True):
                st.session_state["tf"] = _val
                st.cache_data.clear()
                st.rerun()
    tf = st.session_state["tf"]

    def _merge_today_bar(daily_df):
        """Append today's in-progress bar to daily df during trading hours.

        Daily warehouse only updates at end-of-day, so during the session the
        chart's last candle is yesterday — making the dashboard "lie" about
        live price. Aggregate today's 5m intraday into one bar so 1D/1W/1M
        views reflect the current session.

        IMPORTANT: load_intraday returns VCI raw (often VND) while daily
        warehouse is in nghìn đồng (after _normalize_price_units). Merging
        without rescaling produces a chart with one giant bar at 21,850
        next to thousands of bars at ~22 — y-axis auto-scales to 22,000
        so the historical candles compress to a flat line near zero
        (the "1D chart blank" symptom). _normalize_live_price() is the
        existing single-price scaler — apply it to each OHLC value.
        """
        import pandas as _pd
        from datetime import date as _d
        if daily_df is None or daily_df.empty:
            return daily_df
        last_dt = _pd.to_datetime(daily_df["time"].iloc[-1]).date()
        today   = _d.today()
        if last_dt >= today:
            return daily_df  # already includes today
        intra = load_intraday(ticker, interval="5m")
        if intra is None or intra.empty:
            intra = load_intraday(ticker, interval="1D")
        if intra is None or intra.empty:
            return daily_df
        today_bars = intra[intra["time"].dt.date == today]
        if today_bars.empty:
            return daily_df
        # Use last daily close as the unit reference; the helper detects
        # 1000x mismatches and divides/multiplies as needed.
        from vnstock_dashboard import _normalize_live_price as _norm
        ref_close = float(daily_df["close"].iloc[-1])
        today_row = {
            "time":   _pd.Timestamp(today),
            "open":   _norm(ref_close, float(today_bars["open"].iloc[0])),
            "high":   _norm(ref_close, float(today_bars["high"].max())),
            "low":    _norm(ref_close, float(today_bars["low"].min())),
            "close":  _norm(ref_close, float(today_bars["close"].iloc[-1])),
            "volume": float(today_bars["volume"].sum()),
        }
        return _pd.concat([daily_df, _pd.DataFrame([today_row])], ignore_index=True)

    if tf in ("1m","5m","15m","30m","1H"):
        with st.spinner(f"Đang tải {tf} data từ VCI..."):
            chart_df = load_intraday(ticker, interval=tf)
        if chart_df.empty:
            st.warning(f"Không lấy được dữ liệu {tf}. Hiển thị daily.")
            chart_df = _merge_today_bar(df)
    elif tf == "1W":
        # Resample từ daily warehouse (stable hơn API 1W) — merge today first
        chart_df = resample_ohlcv(_merge_today_bar(df), "W")
    elif tf == "1M":
        chart_df = resample_ohlcv(_merge_today_bar(df), "ME")
    else:
        chart_df = _merge_today_bar(df)

    # Surface data range so user can verify live freshness — stale data is
    # the most common cause of "chart không update" reports.
    if not chart_df.empty:
        _t0 = chart_df["time"].iloc[0]
        _t1 = chart_df["time"].iloc[-1]
        _fmt = "%d/%m %H:%M" if tf in ("1m","5m","15m","30m","1H") else "%d/%m/%Y"
        st.caption(
            f"📅 Data: {_t0.strftime(_fmt)} → {_t1.strftime(_fmt)} "
            f"({len(chart_df):,} bars)"
        )

    # ── Live mode: wrap chart + quote strip trong fragment auto-refresh ─────────
    _live_on = st.session_state.get("live_mode", False) and WSS_AVAILABLE
    _live_intraday = _live_on and tf in ("1m","5m","15m","30m","1H")
    _live_daily = _live_on and tf in ("1D","1W","1M","All")

    if _live_intraday:
        # Banner nhắc nhở Live mode đang hoạt động
        st.markdown(
            '<div style="background:linear-gradient(90deg,#ef4444,#f59e0b);'
            'padding:6px 14px;border-radius:6px;margin:8px 0;'
            'display:flex;align-items:center;gap:10px;font-weight:500">'
            '<span style="width:10px;height:10px;border-radius:50%;background:#fff;'
            'box-shadow:0 0 10px #fff;animation:pulse 1.5s infinite"></span>'
            f'<span style="color:#fff;font-size:13px">🔴 LIVE MODE — {ticker} @ {tf} — refresh 3s</span>'
            '</div>',
            unsafe_allow_html=True
        )

        # Quote strip + Order book + VP — refresh every 3s (lightweight)
        @st.fragment(run_every=3)
        def _live_quote_fragment():
            live_q = load_live_quote(ticker)
            _chart_df_tmp = load_intraday(ticker, interval=tf)

            if live_q:
                lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                _price = float(live_q.get("price", 0))
                _chg = float(live_q.get("chg_pct", 0))
                _vol = float(live_q.get("volume", 0))
                _bid = float(live_q.get("bid", 0))
                _ask = float(live_q.get("ask", 0))
                _display_price = _price
                _scale = 1.0
                if not _chart_df_tmp.empty:
                    _last_close = float(_chart_df_tmp.iloc[-1]["close"])
                    _display_price = _normalize_live_price(_last_close, _price)
                    _bid_disp = _normalize_live_price(_last_close, _bid) if _bid else 0
                    _ask_disp = _normalize_live_price(_last_close, _ask) if _ask else 0
                    if _display_price > 0 and _price > 0:
                        _scale = _price / _display_price
                else:
                    _bid_disp, _ask_disp = _bid, _ask
                lc1.metric("💰 Giá Live", f"{_display_price:,.2f}", f"{_chg:+.2f}%")
                lc2.metric("📊 Volume tích luỹ", f"{_vol:,.0f}",
                           help="Tổng khối lượng khớp từ đầu phiên 9:00 tới hiện tại")
                lc3.metric("🟢 Bid (tốt nhất)", f"{_bid_disp:,.2f}" if _bid else "—")
                lc4.metric("🔴 Ask (tốt nhất)", f"{_ask_disp:,.2f}" if _ask else "—")
                lc5.metric("⏱ Cập nhật", str(live_q.get("time", ""))[-8:])

                _bids = live_q.get("bids", [])
                _asks = live_q.get("asks", [])
                _is_fut = is_futures(ticker) or live_q.get("type") == "futures"
                if _bids or _asks:
                    _title = (
                        f"📋 Sổ lệnh (3 mức tốt nhất) — "
                        f"{'Hợp đồng tương lai' if _is_fut else 'Cổ phiếu'}"
                    )
                    render_order_book(
                        _bids, _asks,
                        scale=_scale,
                        max_levels=3,
                        title=_title,
                    )

                _vp = live_q.get("volume_profile", [])
                if not _vp and not _is_fut:
                    _vp = fetch_volume_profile_direct(ticker)
                if _vp:
                    render_volume_profile(
                        _vp,
                        current_price=_price,
                        scale=_scale,
                        max_rows=20,
                    )
            else:
                st.warning(
                    f"⏳ Chưa có dữ liệu live cho {ticker}. "
                    f"Chờ WSS kết nối... (poll mỗi 5s)"
                )

        _live_quote_fragment()

        # Background producer — every 2s, fetch latest intraday bar, merge
        # live WSS quote into it, write to JSON. JS in chart iframe polls
        # this file at the same rate and updates only the last candle (no
        # rebuild, no zoom reset). Cache TTL on load_intraday is 60s but
        # live_quote is WSS-realtime (~100-500ms tick) so close/high/low
        # tick essentially live at the 2s sample rate. Dropping to 1s also
        # works on fast machines; bumped from 5s for TradingView-grade feel.
        @st.fragment(run_every=2)
        def _intraday_bar_writer():
            import json as _json
            from pathlib import Path as _P
            try:
                intra = load_intraday(ticker, interval=tf)
                if intra is None or intra.empty:
                    return
                live_q = load_live_quote(ticker)
                if live_q:
                    intra = _merge_live_quote(intra, live_q)
                last = intra.iloc[-1]
                bar = {
                    "time":   int(last["time"].timestamp()),
                    "open":   float(last["open"]),
                    "high":   float(last["high"]),
                    "low":    float(last["low"]),
                    "close":  float(last["close"]),
                    "volume": float(last["volume"]),
                }
                out = _P(f"static/today_bars/{ticker}_{tf}.json")
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".tmp")
                tmp.write_text(_json.dumps(bar))
                tmp.replace(out)
            except Exception:
                pass
        _intraday_bar_writer()

        # Chart — render OUTSIDE fragment (no flicker, no scroll reset).
        # Merge live quote into chart data on initial render so the very
        # first paint already shows live state; JS polling takes over for
        # subsequent ticks.
        _live_q_chart = load_live_quote(ticker)
        _chart_df_live = load_intraday(ticker, interval=tf)
        if _live_q_chart and not _chart_df_live.empty:
            _chart_df_live = _merge_live_quote(_chart_df_live, _live_q_chart)
        _vp_chart = None
        if _live_q_chart:
            _vp_chart = _live_q_chart.get("volume_profile", [])
            if not _vp_chart and not is_futures(ticker):
                _vp_chart = fetch_volume_profile_direct(ticker)
        try:
            render_chart(_chart_df_live if not _chart_df_live.empty else chart_df,
                         ticker,
                         height=st.session_state.get("chart_height_anal", 850),
                         volume_profile=_vp_chart if _vp_chart else None,
                         live_url=f"/app/static/today_bars/{ticker}_{tf}.json",
                         live_poll_ms=2000)
        except Exception as _e:
            st.error(f"Chart render error: {_e}")

        # Manual refresh button for chart
        if st.button("🔄 Refresh Chart", key="refresh_live_chart"):
            st.cache_data.clear()
            st.rerun()

    # ── Alert checker (runs in background every 10s when live) ────────
    if _live_on:
        @st.fragment(run_every=10)
        def _alert_checker():
            _al = load_alerts()
            _active = [a for a in _al if not a.get("fired")]
            if not _active:
                return
            _tg_t = st.session_state.get("_tg_token", "")
            _tg_c = st.session_state.get("_tg_chat", "")
            updated = check_and_fire_alerts(_al, _tg_t, _tg_c)
            _newly_fired = [a for a in updated
                            if a.get("fired") and a.get("fired_at")
                            and a not in _al]
            # Chỉ save nếu có alert mới triggered
            if any(a.get("fired") and not _al[i].get("fired")
                   for i, a in enumerate(updated) if i < len(_al)):
                save_alerts(updated)
                for a in updated:
                    if a.get("fired") and a.get("message"):
                        if not any(old.get("fired") and old.get("ticker") == a["ticker"]
                                   and old.get("condition") == a["condition"]
                                   for old in _al):
                            st.toast(f"🔔 {a['ticker']}: {a.get('message', 'Alert triggered!')[:100]}")

        _alert_checker()

    # ── Live mode + Daily/Weekly/Monthly chart ────────────────────────────
    if _live_daily:
        st.markdown(
            '<div style="background:linear-gradient(90deg,#3b82f6,#8b5cf6);'
            'padding:6px 14px;border-radius:6px;margin:8px 0;'
            'display:flex;align-items:center;gap:10px;font-weight:500">'
            '<span style="width:10px;height:10px;border-radius:50%;background:#fff;'
            'box-shadow:0 0 10px #fff;animation:pulse 1.5s infinite"></span>'
            f'<span style="color:#fff;font-size:13px">🔴 LIVE — {ticker} @ {tf} — quote strip live</span>'
            '</div>',
            unsafe_allow_html=True
        )

        @st.fragment(run_every=5)
        def _live_daily_quote_fragment():
            live_q = load_live_quote(ticker)
            if live_q:
                _price = float(live_q.get("price", 0))
                _chg = float(live_q.get("chg_pct", 0))
                _vol = float(live_q.get("volume", 0))
                _bid = float(live_q.get("bid", 0))
                _ask = float(live_q.get("ask", 0))
                _time = live_q.get("time", "")

                _chg_color = "#10b981" if _chg >= 0 else "#ef4444"
                _chg_sign = "+" if _chg >= 0 else ""

                st.markdown(
                    f"<div style='display:flex;gap:20px;align-items:center;padding:8px 0;"
                    f"font-family:IBM Plex Mono,monospace'>"
                    f"<div><span style='color:#6b7280;font-size:10px'>GIÁ</span><br>"
                    f"<span style='color:#e5e7eb;font-size:22px;font-weight:700'>{_price:,.2f}</span></div>"
                    f"<div><span style='color:#6b7280;font-size:10px'>%D</span><br>"
                    f"<span style='color:{_chg_color};font-size:16px;font-weight:600'>"
                    f"{_chg_sign}{_chg:.2f}%</span></div>"
                    f"<div><span style='color:#6b7280;font-size:10px'>VOLUME</span><br>"
                    f"<span style='color:#e5e7eb;font-size:14px'>{_vol:,.0f}</span></div>"
                    f"<div><span style='color:#6b7280;font-size:10px'>BID/ASK</span><br>"
                    f"<span style='color:#10b981;font-size:13px'>{_bid:,.0f}</span>"
                    f" / <span style='color:#ef4444;font-size:13px'>{_ask:,.0f}</span></div>"
                    f"<div><span style='color:#6b7280;font-size:10px'>CẬP NHẬT</span><br>"
                    f"<span style='color:#9ca3af;font-size:12px'>{_time[-8:] if _time else '—'}</span></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # Order book + VP cho daily view
                _is_fut = is_futures(ticker) or live_q.get("type") == "futures"
                _bids = live_q.get("bids", [])
                _asks = live_q.get("asks", [])
                if _bids or _asks:
                    render_order_book(
                        _bids, _asks, scale=1.0,
                        max_levels=10 if _is_fut else 3,
                    )

                _vp = live_q.get("volume_profile", [])
                if not _vp and not _is_fut:
                    _vp = fetch_volume_profile_direct(ticker)
                if _vp:
                    render_volume_profile(_vp, current_price=_price, scale=1.0, max_rows=20)

        _live_daily_quote_fragment()

        # Background fragment — writes today's aggregated OHLCV to a static
        # JSON file every 30s. The chart (rendered ONCE outside the fragment)
        # has JS that polls this file and calls candleSeries.update() on the
        # last bar — no iframe rebuild, no zoom reset, no flicker.
        @st.fragment(run_every=30)
        def _today_bar_writer():
            import json as _json
            import sys as _sys
            import pandas as _pd
            from pathlib import Path as _P
            from datetime import date as _d
            try:
                intra = load_intraday(ticker, interval="5m")
                if intra is None or intra.empty:
                    intra = load_intraday(ticker, interval="1D")
                if intra is None or intra.empty:
                    return
                today_bars = intra[intra["time"].dt.date == _d.today()]
                if today_bars.empty:
                    return
                _ref = float(chart_df["close"].iloc[-1]) if not chart_df.empty else 0.0
                bar = {
                    "time":   int(_pd.Timestamp(_d.today()).timestamp()),
                    "open":   _normalize_live_price(_ref, float(today_bars["open"].iloc[0])),
                    "high":   _normalize_live_price(_ref, float(today_bars["high"].max())),
                    "low":    _normalize_live_price(_ref, float(today_bars["low"].min())),
                    "close":  _normalize_live_price(_ref, float(today_bars["close"].iloc[-1])),
                    "volume": float(today_bars["volume"].sum()),
                }
                out = _P("static/today_bars") / f"{ticker}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".tmp")
                tmp.write_text(_json.dumps(bar))
                tmp.replace(out)  # atomic — readers never see partial JSON
            except Exception as _ex:
                print(f"[today_bar_writer] {ticker}: {_ex}", file=_sys.stderr)
        _today_bar_writer()

        # Chart with JS-side live polling — see render_chart docstring.
        render_chart(
            chart_df, ticker,
            height=st.session_state.get("chart_height_anal", 850),
            live_url=f"/app/static/today_bars/{ticker}.json",
        )

    # ── Intraday Replay ───────────────────────────────────────────────────────
    elif (not _live_intraday
          and st.session_state.get("replay_date", "(tắt)") != "(tắt)"
          and st.session_state.get("replay_date")):
        _replay_date = st.session_state["replay_date"]
        _replay_df = load_intraday_bars(ticker, _replay_date)
        if _replay_df.empty:
            st.info(
                f"📼 Không có bars 1m cho **{ticker}** ngày {_replay_date}. "
                f"Có thể mã này chưa được subscribe lúc Live Mode bật."
            )
            # Fallback về chart daily bình thường
            render_chart(chart_df, ticker,
                         height=st.session_state.get("chart_height_anal", 850))
        else:
            st.markdown(
                f'<div style="background:#1e293b;padding:8px 14px;border-radius:6px;'
                f'margin-bottom:8px;font-size:13px;color:#94a3b8">'
                f'📼 <b style="color:#fbbf24">Replay</b> — {ticker} ngày '
                f'{_replay_date} — {len(_replay_df)} bars 1m '
                f'({_replay_df["time"].iloc[0].strftime("%H:%M")} → '
                f'{_replay_df["time"].iloc[-1].strftime("%H:%M")})'
                f'</div>',
                unsafe_allow_html=True,
            )
            render_chart(_replay_df, f"{ticker} · Replay {_replay_date}",
                         height=st.session_state.get("chart_height_anal", 850))
    elif not _live_intraday:
        # Even without Live Mode, write today's bar to JSON every 10s so
        # the chart's JS polling can update the last candle in place.
        # Produces a TradingView-style ticking 1D chart during the session
        # without requiring the user to enable Live Mode (which adds WSS
        # subscription overhead). Daily/weekly/monthly only — intraday
        # timeframes without Live Mode use whatever chart_df was loaded.
        _idle_url = None
        if tf in ("1D", "1W", "1M", "All"):
            @st.fragment(run_every=10)
            def _idle_today_bar_writer():
                import json as _json
                import sys as _sys
                import pandas as _pd
                from pathlib import Path as _P
                from datetime import date as _d
                try:
                    intra = load_intraday(ticker, interval="5m")
                    if intra is None or intra.empty:
                        intra = load_intraday(ticker, interval="1D")
                    if intra is None or intra.empty:
                        return
                    today_bars = intra[intra["time"].dt.date == _d.today()]
                    if today_bars.empty:
                        return
                    _ref = float(chart_df["close"].iloc[-1]) if not chart_df.empty else 0.0
                    bar = {
                        "time":   int(_pd.Timestamp(_d.today()).timestamp()),
                        "open":   _normalize_live_price(_ref, float(today_bars["open"].iloc[0])),
                        "high":   _normalize_live_price(_ref, float(today_bars["high"].max())),
                        "low":    _normalize_live_price(_ref, float(today_bars["low"].min())),
                        "close":  _normalize_live_price(_ref, float(today_bars["close"].iloc[-1])),
                        "volume": float(today_bars["volume"].sum()),
                    }
                    out = _P("static/today_bars") / f"{ticker}.json"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    tmp = out.with_suffix(".tmp")
                    tmp.write_text(_json.dumps(bar))
                    tmp.replace(out)
                except Exception as _ex:
                    print(f"[idle_today_bar_writer] {ticker}: {_ex}", file=_sys.stderr)
            _idle_today_bar_writer()
            _idle_url = f"/app/static/today_bars/{ticker}.json"

        try:
            render_chart(chart_df, ticker,
                         height=st.session_state.get("chart_height_anal", 850),
                         live_url=_idle_url,
                         live_poll_ms=10000)
        except Exception as _e:
            st.error(
                f"Chart render error ({tf}, {len(chart_df)} bars): "
                f"{type(_e).__name__}: {_e}"
            )
            import traceback as _tb
            with st.expander("Stack trace"):
                st.code(_tb.format_exc())

    st.markdown("---")

    # ── Technical + Fundamental side by side ─────────────────────────────────────
    col_tech, col_fund = st.columns([1, 1])

    with col_tech:
        st.markdown('<p class="section-title">📈 Phân tích kỹ thuật</p>', unsafe_allow_html=True)

        # RSI gauge
        rsi = tech.get("rsi")
        if rsi:
            rsi_color = "#10b981" if rsi < 30 else ("#ef4444" if rsi > 70 else "#fbbf24")
            st.markdown(
                f'<div class="card">'
                f'<div class="card-title">RSI (14)</div>'
                f'<div style="font-family:IBM Plex Mono,monospace;font-size:32px;'
                f'font-weight:500;color:{rsi_color}">{rsi:.1f}</div>'
                f'<div class="fscore-bar"><div class="fscore-fill" style="width:{rsi}%;background:{rsi_color}"></div></div>'
                f'<div style="font-size:11px;color:#6b7280;display:flex;justify-content:space-between">'
                f'<span>Oversold &lt;30</span><span>Overbought &gt;70</span></div>'
                f'</div>',
                unsafe_allow_html=True
            )

        # Signals
        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_signal_badge("RSI Signal",  tech.get("rsi_sig",  "NEUTRAL"))
        render_signal_badge("MACD Signal", tech.get("macd_sig", "NEUTRAL"))
        render_signal_badge("EMA Trend",   tech.get("ema_sig",  "NEUTRAL"))
        render_signal_badge("BB Signal",   tech.get("bb_sig",   "NEUTRAL"))
        st.markdown('</div>', unsafe_allow_html=True)

        # EMA levels
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">EMA Levels</div>', unsafe_allow_html=True)
        for span, val in [("EMA 9", tech.get("ema9")), ("EMA 21", tech.get("ema21")),
                           ("EMA 50", tech.get("ema50")), ("EMA 200", tech.get("ema200"))]:
            if val:
                diff = round((price - val) / val * 100, 2)
                color = "#10b981" if price > val else "#ef4444"
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:5px 0;border-bottom:1px solid #1a2234;font-size:13px">'
                    f'<span style="color:#9ca3af">{span}</span>'
                    f'<span style="color:#e5e7eb">{val:,.2f}</span>'
                    f'<span style="color:{color}">{fmt_pct(diff)}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        st.markdown('</div>', unsafe_allow_html=True)

        # Volume
        vol = tech.get("vol")
        vol_ma = tech.get("vol_ma20")
        vol_spike = tech.get("vol_spike")
        if vol and vol_ma:
            spike_color = "#f97316" if vol_spike and vol_spike > 2 else "#9ca3af"
            st.markdown(
                f'<div class="card">'
                f'<div class="card-title">Volume</div>'
                f'<div style="font-size:16px;color:#e5e7eb">{vol/1e6:.1f}M</div>'
                f'<div style="font-size:12px;color:{spike_color};margin-top:4px">'
                f'Vol spike: {vol_spike:.1f}× MA20</div>'
                f'</div>',
                unsafe_allow_html=True
            )

        # Tech score
        ts = tech.get("tech_score", 0)
        ts_color = "#10b981" if ts > 0.2 else ("#ef4444" if ts < -0.2 else "#fbbf24")
        ts_label = "BULLISH" if ts > 0.2 else ("BEARISH" if ts < -0.2 else "NEUTRAL")
        st.markdown(
            f'<div class="card">'
            f'<div class="card-title">Technical Score</div>'
            f'<div style="font-family:IBM Plex Mono,monospace;font-size:28px;color:{ts_color}">'
            f'{ts:+.2f}</div>'
            f'<div style="font-size:12px;color:{ts_color};font-weight:600">{ts_label}</div>'
            f'</div>',
            unsafe_allow_html=True
        )


    with col_fund:
        st.markdown('<p class="section-title">🏦 Phân tích cơ bản</p>', unsafe_allow_html=True)

        if load_fund:
            with st.spinner("Đang tải dữ liệu cơ bản từ API..."):
                fund = load_fundamental(ticker)

            # Debug: show raw result
            if fund:
                non_none = {k:v for k,v in fund.items() if v is not None and k != "_cols_debug"}
                if not non_none or (len(non_none)==1 and "error" in non_none):
                    cols_info = fund.get("_cols_debug", [])
                    st.warning(f"⚠ Không lấy được dữ liệu cơ bản. Columns: {cols_info}")
                elif fund.get("error"):
                    st.warning(f"Lỗi: {fund['error']}")
                # Debug expander when key metrics are missing
                _missing = [k for k in ("eps", "book_value") if fund.get(k) is None]
                if _missing and not fund.get("error"):
                    with st.expander(f"🔍 Debug: {', '.join(_missing)} = None"):
                        _oc = fund.get("_overview_cols", [])
                        _rc = fund.get("_ratio_cols", [])
                        st.caption(f"Overview cols ({len(_oc)}): {_oc}")
                        st.caption(f"Ratio cols ({len(_rc)}): {_rc}")
            else:
                st.warning("⚠ load_fundamental() trả về rỗng")

            if fund.get("error"):
                pass  # already shown above
            elif fund:
                # Key ratios
                # Thông tin doanh nghiệp
                _mktcap = fund.get("market_cap")
                _shares = fund.get("shares_outstanding")
                _listed = fund.get("shares_listed")
                _avgvol = fund.get("avg_vol_10")
                if _mktcap or _shares or _avgvol:
                    st.markdown('<div class="card">', unsafe_allow_html=True)
                    st.markdown('<div class="card-title">Thông tin doanh nghiệp</div>', unsafe_allow_html=True)
                    _info_items = [
                        ("Vốn hoá TT", _mktcap, "tỷ", lambda v: f"{v/1e9:,.1f}" if v and v > 1e6 else (f"{v:,.1f}" if v else None)),
                        ("KLCP lưu hành", _shares, "CP", lambda v: f"{v:,.0f}" if v else None),
                        ("KLCP niêm yết", _listed, "CP", lambda v: f"{v:,.0f}" if v else None),
                        ("KL khớp TB 10 phiên", _avgvol, "", lambda v: f"{v:,.0f}" if v else None),
                    ]
                    for label, val, unit, fmt_fn in _info_items:
                        if val is not None:
                            display = fmt_fn(val) if fmt_fn else f"{val:,.2f}"
                            if display:
                                st.markdown(
                                    f'<div style="display:flex;justify-content:space-between;'
                                    f'padding:4px 0;border-bottom:1px solid #1a2234;font-size:13px">'
                                    f'<span style="color:#9ca3af">{label}</span>'
                                    f'<span style="color:#e5e7eb;font-family:IBM Plex Mono,monospace">'
                                    f'{display} {unit}</span></div>',
                                    unsafe_allow_html=True
                                )
                    st.markdown('</div>', unsafe_allow_html=True)

                st.markdown('<div class="card">', unsafe_allow_html=True)
                st.markdown('<div class="card-title">Định giá & Sinh lời</div>', unsafe_allow_html=True)
                ratios = [
                    ("EPS",              fund.get("eps"),            "đ"),
                    ("Book Value",       fund.get("book_value"),     "đ"),
                    ("P/E",              fund.get("pe"),             "lần"),
                    ("P/B",              fund.get("pb"),             "lần"),
                    ("Earnings Yield",   fund.get("earnings_yield"), "%"),
                    ("Cổ tức",           fund.get("dividend_yield"), "%"),
                    ("ROE",              fund.get("roe"),            "%"),
                    ("ROA",              fund.get("roa"),            "%"),
                    ("Biên LN gộp",      fund.get("gross_margin"),   "%"),
                    ("Biên LN hoạt động", fund.get("operating_margin"), "%"),
                    ("Biên LN ròng",     fund.get("net_margin"),     "%"),
                    ("Tỷ lệ nợ/TS",      fund.get("debt_ratio") or None,     ""),
                    ("Nợ/VCSH",          fund.get("debt_to_equity") or None, "lần"),
                    ("Thanh toán HH",    fund.get("current_ratio") or None,  "lần"),
                    ("Thanh toán nhanh", fund.get("quick_ratio") or None,    "lần"),
                    ("Vòng quay TS",     fund.get("asset_turnover") or None, "lần"),
                    ("Tăng trưởng DT",   fund.get("revenue_growth"), "%"),
                    ("Tăng trưởng LN",   fund.get("profit_growth"),  "%"),
                ]
                for label, val, unit in ratios:
                    if val is not None:
                        color = "#e5e7eb"
                        if label in ("ROE","ROA") and val > 15: color = "#10b981"
                        if label == "Tăng trưởng DT":
                            color = "#10b981" if val > 0 else "#ef4444"
                        if label == "P/E" and val < 15: color = "#10b981"
                        if label == "P/E" and val > 30: color = "#ef4444"
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;'
                            f'padding:6px 0;border-bottom:1px solid #1a2234;font-size:13px">'
                            f'<span style="color:#9ca3af">{label}</span>'
                            f'<span style="color:{color};font-family:IBM Plex Mono,monospace">'
                            f'{val:.2f} {unit}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                st.markdown('</div>', unsafe_allow_html=True)

            # Fund score từ ratios
            fund_score = None
            if not fund.get("error"):
                pts = 0; cnt = 0
                if fund.get("roe") and fund["roe"] > 15:   pts += 1; cnt += 1
                elif fund.get("roe"):                        cnt += 1
                if fund.get("roa") and fund["roa"] > 5:    pts += 1; cnt += 1
                elif fund.get("roa"):                        cnt += 1
                if fund.get("pe") and 0 < fund["pe"] < 20: pts += 1; cnt += 1
                elif fund.get("pe"):                         cnt += 1
                if fund.get("revenue_growth") and fund["revenue_growth"] > 0: pts += 1; cnt += 1
                elif fund.get("revenue_growth") is not None: cnt += 1
                if fund.get("net_margin") and fund["net_margin"] > 10: pts += 1; cnt += 1
                elif fund.get("net_margin"):                  cnt += 1

                if cnt > 0:
                    fund_score = round((pts / cnt) * 2 - 1, 2)
                    fs_color = "#10b981" if fund_score > 0.2 else ("#ef4444" if fund_score < -0.2 else "#fbbf24")
                    fs_label = "STRONG" if fund_score > 0.5 else ("GOOD" if fund_score > 0.2 else ("WEAK" if fund_score < -0.2 else "FAIR"))
                    st.markdown(
                        f'<div class="card">'
                        f'<div class="card-title">Fundamental Score</div>'
                        f'<div style="font-family:IBM Plex Mono,monospace;font-size:28px;color:{fs_color}">'
                        f'{fund_score:+.2f}</div>'
                        f'<div style="font-size:12px;color:{fs_color};font-weight:600">{fs_label} ({pts}/{cnt} tiêu chí)</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

        else:
            st.markdown(
                '<div class="card" style="border:1px dashed #374151">'
                '<div class="card-title">Dữ liệu cơ bản</div>'
                '<div style="color:#6b7280;font-size:13px;line-height:1.7">'
                'Bật toggle <strong style="color:#9ca3af">Tải dữ liệu cơ bản</strong> ở sidebar '
                'để xem P/E, ROE, EPS và các chỉ số tài chính khác.'
                '</div></div>',
                unsafe_allow_html=True
            )

        # Consensus
        ts = tech.get("tech_score", 0)
        fund_score_val = fund_score if load_fund and not fund.get("error") and fund_score is not None else 0
        weight_t, weight_f = (0.5, 0.5) if not load_fund else (0.4, 0.6)
        composite = round(ts * weight_t + fund_score_val * weight_f, 2)

        rec_label = (
            "STRONG BUY 🟢🟢" if composite > 0.6 else
            "BUY 🟢"          if composite > 0.2 else
            "HOLD 🟡"         if composite >= -0.2 else
            "SELL 🔴"         if composite >= -0.6 else
            "STRONG SELL 🔴🔴"
        )
        rec_color = "#10b981" if composite > 0.2 else ("#ef4444" if composite < -0.2 else "#fbbf24")

        st.markdown(
            f'<div class="card" style="border:1px solid {rec_color}40;margin-top:12px">'
            f'<div class="card-title">Khuyến nghị tổng hợp '
            f'{"(40% tech + 60% fund)" if load_fund else "(chỉ technical)"}'
            f'</div>'
            f'<div style="font-size:24px;font-weight:600;color:{rec_color};margin:8px 0">'
            f'{rec_label}</div>'
            f'<div style="font-size:12px;color:#6b7280">'
            f'Composite score: <span style="color:{rec_color};font-family:IBM Plex Mono">'
            f'{composite:+.2f}</span></div>'
            f'</div>',
            unsafe_allow_html=True
        )

        # ── AI Strategy Recommendation ─────────────────────────────────────────
        st.markdown(
            '<div style="margin-top:20px;font-size:16px;font-weight:600">🤖 Khuyến nghị từ AI Strategy</div>',
            unsafe_allow_html=True,
        )

        try:
            import vnstock_memory as _vm_ai
            _vm_ai.init_db()
            _active_strat = _vm_ai.get_active_family()
        except Exception:
            _active_strat = None

        _ai_cache_key = f"_ai_rec_{ticker}"

        if not _active_strat:
            st.info(
                "Chưa có chiến lược AI nào. "
                "Vào tab **Thị trường → 🧪 Chiến lược & khuyến nghị** → nhấn **Lite training**.",
                icon="ℹ️",
            )
        else:
            _cached_rec = st.session_state.get(_ai_cache_key)
            _strat_id   = _active_strat.get("id")
            _is_fresh   = (
                _cached_rec is not None
                and _cached_rec.get("strategy_id") == _strat_id
                and _cached_rec.get("_ticker") == ticker
            )

            # Warn if strategy has 0 trades
            _strat_nt = 0
            try:
                _fh_ai = _vm_ai.family_history(_active_strat.get("family_id", ""), limit=1)
                _strat_nt = int((_fh_ai[0].get("n_trades") or 0) if _fh_ai else 0)
            except Exception:
                pass
            if _strat_nt == 0:
                st.warning(
                    "Chiến lược hiện tại có **0 trades** trong backtest — tín hiệu có thể chưa chính xác. "
                    "Nhấn **Fresh start** trong tab Thị trường để cải thiện.",
                    icon="⚠️",
                )

            if _is_fresh:
                _r   = _cached_rec
                _act = _r.get("action", "hold")
                _col = "#10b981" if _act == "buy" else ("#ef4444" if _act == "sell" else "#fbbf24")
                _act_label = {"buy": "MUA 🟢", "sell": "BÁN 🔴"}.get(_act, "KHÔNG GIAO DỊCH 🟡")

                # ── Consensus badge (multi-agent) ──────────────────────────
                _votes = _r.get("votes", [])
                _n_ag  = _r.get("n_agents", 0)
                _cons_act = _r.get("consensus_action", _act)
                _agree_rt = _r.get("agreement_rate", 1.0)
                _strat_agree = _r.get("strategy_agree_rate")

                if _n_ag > 1:
                    _cons_label = {"buy": "MUA 🟢", "sell": "BÁN 🔴"}.get(_cons_act, "KHÔNG GIAO DỊCH 🟡")
                    _cons_col   = "#10b981" if _cons_act == "buy" else ("#ef4444" if _cons_act == "sell" else "#fbbf24")
                    _agree_pct  = int(_agree_rt * 100)
                    _strat_pct  = int((_strat_agree or 0) * 100)
                    _badge_col  = "#10b981" if _agree_pct >= 67 else ("#fbbf24" if _agree_pct >= 34 else "#ef4444")
                    st.markdown(
                        f'<div class="card" style="border:1px solid {_cons_col}60;margin-top:8px">'
                        f'<div class="card-title" style="font-size:11px">'
                        f'Đồng thuận {_n_ag} agents · {_r.get("strategy_name","—")}'
                        f'</div>'
                        f'<div style="font-size:26px;font-weight:700;color:{_cons_col};margin:6px 0">'
                        f'{_cons_label}</div>'
                        f'<div style="display:flex;gap:16px;margin-top:4px">'
                        f'<span style="font-size:12px;color:{_badge_col};font-weight:600">'
                        f'🗳 Đồng thuận: {_agree_pct}%</span>'
                        f'<span style="font-size:12px;color:#6b7280">'
                        f'Tin strategy: {_strat_pct}%</span>'
                        f'<span style="font-size:12px;color:#6b7280">'
                        f'Signal conf: {_r.get("confidence",0):.0%}</span>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                    # Per-agent votes table
                    if _votes:
                        with st.expander("Xem chi tiết từng agent", expanded=False):
                            for _v in _votes:
                                _va  = _v.get("action", "hold")
                                _vc  = "#10b981" if _va == "buy" else ("#ef4444" if _va == "sell" else "#fbbf24")
                                _val = {"buy": "MUA 🟢", "sell": "BÁN 🔴"}.get(_va, "KHÔNG GD 🟡")
                                _agr = "✅" if _v.get("agrees") else ("❌" if _v.get("agrees") is False else "—")
                                st.markdown(
                                    f'**{_v["agent"]}** — {_val} {_agr} '
                                    f'<span style="color:#6b7280;font-size:12px">'
                                    f'{_v.get("reason","")}</span>',
                                    unsafe_allow_html=True,
                                )
                else:
                    # Single agent — original card
                    st.markdown(
                        f'<div class="card" style="border:1px solid {_col}60;margin-top:8px">'
                        f'<div class="card-title" style="font-size:11px">{_r.get("strategy_name","—")}</div>'
                        f'<div style="font-size:26px;font-weight:700;color:{_col};margin:6px 0">{_act_label}</div>'
                        f'<div style="font-size:12px;color:#6b7280">Confidence: {_r.get("confidence",0):.0%}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # ── Entry / TP / SL metrics ────────────────────────────────
                if _act in ("buy", "sell"):
                    _e  = _r.get("entry")
                    _tp = _r.get("tp")
                    _sl = _r.get("sl")
                    _mc1, _mc2, _mc3 = st.columns(3)
                    _mc1.metric("📍 Entry", f"{_e:,.0f}" if _e else "—")
                    _mc2.metric(
                        "🎯 Take Profit", f"{_tp:,.0f}" if _tp else "—",
                        delta=f"{(_tp / _e - 1)*100:+.1f}%" if _tp and _e else None,
                    )
                    _mc3.metric(
                        "🛑 Cut Loss", f"{_sl:,.0f}" if _sl else "—",
                        delta=f"{(_sl / _e - 1)*100:+.1f}%" if _sl and _e else None,
                        delta_color="inverse",
                    )

                if _r.get("explanation"):
                    st.markdown(_r["explanation"])

                if st.button("🔄 Phân tích lại", key="_ai_rec_refresh",
                             help="Gọi AI phân tích lại với dữ liệu mới nhất"):
                    if _ai_cache_key in st.session_state:
                        del st.session_state[_ai_cache_key]
                    st.rerun()

            else:
                from vnstock_brief import build_agents as _build_agents
                _all_agents  = _build_agents()
                _avail_agents = [a for a in _all_agents if a.is_available]
                _n_avail = len(_avail_agents)
                _btn_label = (
                    f"🤖 Phân tích {ticker} ({_n_avail} agents đồng thuận)"
                    if _n_avail > 1 else
                    f"🤖 Phân tích {ticker} với AI Strategy"
                )
                _spinner_msg = (
                    f"⏳ {_n_avail} agents đang vote độc lập… (~{_n_avail * 10}-{_n_avail * 20}s)"
                    if _n_avail > 1 else
                    f"⏳ AI đang phân tích {ticker}… (~10-20s)"
                )
                if st.button(_btn_label, key="_ai_rec_btn", type="primary",
                             help="Strategy signal + vote đồng thuận từ tất cả agents"):
                    with st.spinner(_spinner_msg):
                        try:
                            from vnstock_strategy import (
                                analyze_ticker as _analyze_single,
                                analyze_ticker_consensus as _analyze_consensus,
                            )
                            if _n_avail > 1:
                                _rec_result = _analyze_consensus(_avail_agents, ticker, df)
                            else:
                                _rec_result = _analyze_single(
                                    _avail_agents[0] if _avail_agents else None,
                                    ticker, df,
                                )
                            _rec_result["_ticker"] = ticker
                            st.session_state[_ai_cache_key] = _rec_result
                            st.rerun()
                        except Exception as _ai_err:
                            st.error(f"Lỗi phân tích: {type(_ai_err).__name__}: {_ai_err}")

        # ── Tin tức theo mã ────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🗞️ Tin tức liên quan")
        try:
            import vnstock_news as _nn
            _ticker_news = _nn.news_for_ticker(ticker)
            if not _ticker_news:
                _all_cached = _nn.load_news_cache()
                if _all_cached:
                    st.caption(
                        f"Không có tin tức cho **{ticker}** trong cache. "
                        "Vào tab **Tin tức** → bấm **🔄 Cập nhật** để tải về."
                    )
                else:
                    st.caption(
                        "Chưa có cache tin tức. Vào tab **Tin tức** → bấm **🔄 Cập nhật tin tức**."
                    )
            else:
                st.caption(f"**{len(_ticker_news)}** tin tức gần đây cho {ticker}")
                for _ni, _nitem in enumerate(_ticker_news[:5]):
                    _ntitle = _nitem.get("news_title", "").strip()
                    _nshort = (_nitem.get("news_short_content")
                               or _nitem.get("news_sub_title") or "").strip()
                    _nfull  = (_nitem.get("news_full_content") or "").strip()
                    _nlink  = _nitem.get("news_source_link", "")
                    _ndate  = _nitem.get("_date_sort", "")[:10]
                    if not _ntitle:
                        continue
                    with st.container():
                        st.markdown(f"**{_ntitle}** <span style='color:#6b7280;font-size:12px'>{_ndate}</span>",
                                    unsafe_allow_html=True)
                        if _nshort:
                            st.caption(_nshort[:250])
                        _nc1, _nc2 = st.columns([2, 8])
                        if _nfull and _nfull != _nshort:
                            with _nc1:
                                with st.expander("📖 Đọc thêm"):
                                    st.markdown(_nfull[:2000])
                        if _nlink:
                            with _nc2:
                                st.markdown(f"[🔗 Nguồn gốc]({_nlink})")
        except Exception as _ne:
            st.caption(f"Không tải được tin tức: {type(_ne).__name__}")
