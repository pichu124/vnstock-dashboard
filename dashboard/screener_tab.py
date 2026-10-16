"""
Screener tab — 📊 preset filter browser with live-scan overlay.

Extracted from ``vnstock_dashboard.py`` as part of the tab-modularisation
effort (docs/REFACTOR_PLAN.md). Streamlit is imported lazily inside the
render function so the module is importable by unit tests without the
Streamlit runtime.

All dashboard-level helpers (``df_from_preset``, ``render_table``,
``load_watchlist`` etc.) are lazy-imported from ``vnstock_dashboard``
inside the render function. The circular dependency is safe because the
tab is only dispatched after ``vnstock_dashboard`` has finished loading.

Contract
--------
Inputs (keyword-only — the caller must have already loaded presets /
aggregates at the top of the dashboard):
* ``presets_data``       — dict[name → {results, count, desc}]
* ``industry_summary``   — dict[industry → count]
* ``gen_time``           — ISO string shown in the Alerts expander
* ``total_tickers``      — metric card
* ``classified``         — metric card
* ``total_hits``         — metric card
* ``top_preset``         — (name, preset_dict) tuple for the 4th card
"""

from __future__ import annotations


def render_screener_tab(
    *,
    presets_data: dict,
    industry_summary: dict,
    gen_time: str,
    total_tickers: int,
    classified: int,
    total_hits: int,
    top_preset: tuple,
) -> None:
    """Render the Screener tab. Lazy imports Streamlit + dashboard helpers."""
    try:
        import streamlit as st
    except ImportError:
        print("[screener_tab] streamlit not available")
        return

    # Third-party deps the block uses
    import json
    import numpy as np
    import pandas as pd

    # Dashboard-level helpers — lazy import to avoid circular deps at load.
    # Streamlit registers vnstock_dashboard under various names (__main__, main,
    # vnstock_dashboard) depending on version; probe sys.modules to find it.
    import sys as _sys

    def _get_vnd():
        for _name in ('vnstock_dashboard', '__main__', 'main'):
            _m = _sys.modules.get(_name)
            if _m and hasattr(_m, 'PRESET_ICONS'):
                return _m
        # Last-resort: fresh import (works outside Streamlit / in tests)
        import vnstock_dashboard as _vd
        return _vd

    _vnd = _get_vnd()
    PRESET_ICONS           = _vnd.PRESET_ICONS
    WSS_AVAILABLE          = _vnd.WSS_AVAILABLE
    INDEX_SYMBOLS          = _vnd.INDEX_SYMBOLS
    _is_stock              = _vnd._is_stock
    _normalize_price_units = _vnd._normalize_price_units
    load_watchlist         = _vnd.load_watchlist
    save_watchlist         = _vnd.save_watchlist
    compute_alerts         = _vnd.compute_alerts
    df_from_preset         = _vnd.df_from_preset
    render_table           = _vnd.render_table
    SESSION_WINDOWS        = _vnd.SESSION_WINDOWS
    save_session_stats     = _vnd.save_session_stats
    load_session_stats_history  = _vnd.load_session_stats_history
    render_session_stats_table  = _vnd.render_session_stats_table
    try:
        from vnstock_session_stats import compute_session_stats
        from vnstock_session_stats import backfill_session_stats as _backfill_session_stats
        from vnstock_session_stats import reconcile_with_price_history as _reconcile_eod
    except Exception:
        def compute_session_stats(): return {}
        def _backfill_session_stats(): return 0
        def _reconcile_eod(): return 0
    # Fragment Thống kê phiên chạy mỗi 30s + mỗi lượt rerun trang (Screener là tab
    # mặc định) kể cả khi expander đóng ⇒ đệm 60s phần tính (4× intraday mỗi lượt).
    compute_session_stats = st.cache_data(ttl=60, show_spinner=False)(compute_session_stats)
    from datetime import datetime


    # Sidebar filters (chỉ hiện khi ở tab screener)
    with st.sidebar:
        st.markdown("### 📊 Screener")
        preset_options = list(presets_data.keys())
        selected_preset = st.selectbox(
            "Preset", preset_options,
            format_func=lambda p: f"{PRESET_ICONS.get(p, '')} {p} ({presets_data[p].get('count', 0)})",
            key="scr_preset",
        )
        industries = ["Tất cả"] + list(industry_summary.keys())
        selected_industry = st.selectbox("Ngành", industries, key="scr_industry")
        top_n = st.slider("Hiển thị top", 10, 100, 50, step=10, key="scr_top_n")

        st.divider()
        st.markdown("### ⭐ Watchlist")
        _wl_tickers, _filter_wl = _render_watchlist_sidebar(
            st, load_watchlist, save_watchlist, _vnd.WATCHLIST_PATH)

        st.divider()
        st.markdown("### ⚙️ Bộ lọc nâng cao")
        price_min    = st.number_input("Giá từ (nghìn đồng)", min_value=0.0, value=0.0, step=1.0, format="%.1f", key="scr_price_min")
        price_max    = st.number_input("Giá đến", min_value=0.0, value=0.0, step=1.0, format="%.1f", help="0 = không giới hạn", key="scr_price_max")
        chg1d_range  = st.slider("1D%", -20.0, 20.0, (-20.0, 20.0), step=0.5, format="%.1f%%", key="scr_chg1d")
        chg5d_range  = st.slider("5D%", -50.0, 50.0, (-50.0, 50.0), step=1.0, format="%.1f%%", key="scr_chg5d")
        chg20d_range = st.slider("20D%", -80.0, 150.0, (-80.0, 150.0), step=1.0, format="%.1f%%", key="scr_chg20d")
        vol_min      = st.slider("Volume spike tối thiểu (×)", 0.0, 10.0, 0.0, step=0.5, format="%.1fx", key="scr_vol_min")

        st.divider()
        if industry_summary:
            st.markdown("### 🏭 Phân bố ngành")
            for ind, cnt in list(industry_summary.items())[:10]:
                pct = cnt / classified * 100 if classified else 0
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;font-size:12px;color:#9ca3af;margin:3px 0'>"
                    f"<span>{ind[:22]}</span><span style='color:#6ee7b7;font-family:monospace'>{cnt}</span></div>",
                    unsafe_allow_html=True
                )
                st.progress(pct / 100)

    # ── 📋 Preset scorecard — alpha 30 ngày + "đọc kết quả" deterministic ──
    with st.expander("📋 Chấm điểm preset — alpha ~30 ngày so VNINDEX", expanded=False):
        try:
            import pandas as _pd
            import vnstock_preset_score as _psc
            _card = _psc.load_scorecard()
            if st.button("🔄 Tính lại từ screener_history", key="_psc_refresh",
                         help="Quét ~30 snapshot + kho giá (mất ~30-60s). "
                              "Zero LLM — chỉ số học."):
                with st.spinner("Đang chấm 9 preset (forward return vs VNINDEX)…"):
                    _card = _psc.preset_scorecard()
                    if _card:
                        _psc.save_scorecard(_card)
            if not _card:
                st.info("Chưa có scorecard — bấm 🔄 Tính lại "
                        "(cần screener_history đủ ~6 phiên trở lên).")
            else:
                _hs = _card.get("horizons") or [5, 20]
                _rows = []
                for _name, _row in sorted(
                        _card["presets"].items(),
                        key=lambda kv: (kv[1].get(f"h{_hs[0]}") or {}).get("avg_excess", -99),
                        reverse=True):
                    _r = {"Preset": _name}
                    for _h in _hs:
                        _s = _row.get(f"h{_h}")
                        if _s:
                            _r[f"Excess {_h}p %"] = _s["avg_excess"]
                            _r[f"Hit {_h}p %"] = _s["hit_rate"]
                            _r[f"n {_h}p"] = _s["n"]
                    _rows.append(_r)
                st.dataframe(_pd.DataFrame(_rows), use_container_width=True,
                             hide_index=True)
                st.caption(f"Cập nhật {_card.get('as_of')} · {_card.get('n_days')} "
                           f"snapshot · excess = return rổ hit − VNINDEX cùng cửa sổ "
                           f"· hit = % tín hiệu thắng index")
                _bullets = _psc.interpret_scorecard(
                    _card, breadth_pct=_psc._breadth_pct())
                if _bullets:
                    st.markdown("**🧭 Đọc kết quả** *(suy từ số liệu, không LLM)*:")
                    for _b in _bullets:
                        st.markdown(f"- {_b}")
        except Exception as _e:
            st.caption(f"⚠ preset scorecard lỗi: {type(_e).__name__}: {_e}")

    # ── Live Screener (real-time scan trong phiên) ──────────────────────
    # 05/10: công tắc Live Scan GỘP về sidebar chung (dưới 🔴 Live Mode) —
    # toggle riêng trong tab bị Streamlit dọn state mỗi lần rời tab. Tab chỉ
    # ĐỌC cờ; vẫn gác thêm động cơ live_mode cho chắc.
    _wss_engine_on = bool(st.session_state.get("live_mode")) and WSS_AVAILABLE
    _live_scan_on = bool(st.session_state.get("live_scan")) and _wss_engine_on
    if not _live_scan_on:
        st.caption("🔴 Live Scan đang tắt — bật **Live Scan** ở sidebar trái "
                   "(dưới Live Mode; cần bật **Real-time WSS** trước).")

    if _live_scan_on and WSS_AVAILABLE:
        @st.fragment(run_every=10)
        def _live_screener_fragment():
            import glob as _gl
            from pathlib import Path as _P
            from vnstock_screener import PRESETS

            # Đọc tất cả quote files hiện có
            quote_dir = _P("data_warehouse/_live")
            if not quote_dir.exists():
                st.caption("⏳ Chưa có quote data — bật Live Mode trước")
                return

            live_hits = {p: [] for p in PRESETS if p != "value"}
            quote_files = list(quote_dir.glob("quote_*.json"))
            if not quote_files:
                st.caption("⏳ Chưa có quote data — chờ WSS poll...")
                return

            # Load warehouse data cho mỗi ticker (cached), merge live price
            _screener_cache_key = "live_screener_warehouse"
            if _screener_cache_key not in st.session_state:
                st.session_state[_screener_cache_key] = {}
            _ws_cache = st.session_state[_screener_cache_key]

            scanned = 0
            for qf in quote_files:
                try:
                    ticker_name = qf.stem.replace("quote_", "")
                    # Lọc: chỉ giữ cổ phiếu thật (bỏ futures, index, warrant, CW, bond)
                    if not _is_stock(ticker_name) or ticker_name in INDEX_SYMBOLS:
                        continue

                    live_q = json.loads(qf.read_text())
                    live_price = float(live_q.get("price", 0))
                    live_vol = float(live_q.get("volume", 0))
                    if live_price <= 0:
                        continue

                    # Normalize live price: API trả VND (77700), warehouse dùng nghìn VND (77.7)
                    if live_price > 500:
                        live_price /= 1000

                    # Load historical indicators từ warehouse (cache in session)
                    if ticker_name not in _ws_cache:
                        _ticker_dir = _P("data_warehouse/prices") / f"ticker={ticker_name}"
                        if not _ticker_dir.exists():
                            continue
                        try:
                            import pyarrow.parquet as _pq
                            _frames = []
                            for _yd in sorted(_ticker_dir.iterdir()):
                                if not _yd.is_dir():
                                    continue
                                for _pf in _yd.glob("*.parquet"):
                                    _frames.append(
                                        _pq.read_table(str(_pf),
                                            columns=["time","open","high","low","close","volume"]
                                        ).to_pandas()
                                    )
                            if not _frames:
                                continue
                            _hist = pd.concat(_frames, ignore_index=True)
                            _hist["time"] = pd.to_datetime(_hist["time"])
                            _hist = _hist.sort_values("time").tail(300).reset_index(drop=True)
                            # Normalize warehouse: có thể pha trộn VND + nghìn VND
                            _hist = _normalize_price_units(_hist)
                            _ws_cache[ticker_name] = _hist
                        except Exception:
                            continue

                    hist = _ws_cache.get(ticker_name)
                    if hist is None or len(hist) < 60:
                        continue

                    # Append live price as latest row (đã normalize ở trên)
                    df_live = hist.copy()
                    df_live.iloc[-1, df_live.columns.get_loc("close")] = live_price
                    if live_vol > 0:
                        df_live.iloc[-1, df_live.columns.get_loc("volume")] = live_vol

                    # Compute indicators
                    c = df_live["close"].astype(float)
                    delta = c.diff()
                    gain = delta.clip(lower=0).rolling(14).mean()
                    loss = (-delta.clip(upper=0)).rolling(14).mean()
                    rsi = (100 - (100 / (1 + gain / loss.replace(0, np.nan)))).iloc[-1]

                    ema9 = c.ewm(span=9, adjust=False).mean().iloc[-1]
                    ema21 = c.ewm(span=21, adjust=False).mean().iloc[-1]
                    ema50 = c.ewm(span=50, adjust=False).mean().iloc[-1]
                    ema200 = c.ewm(span=200, adjust=False).mean().iloc[-1]

                    ema12 = c.ewm(span=12, adjust=False).mean()
                    ema26 = c.ewm(span=26, adjust=False).mean()
                    macd_hist = ((ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()).iloc[-1]
                    macd_hist_prev = ((ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()).iloc[-2]

                    vol_ma20 = df_live["volume"].astype(float).rolling(20).mean().iloc[-1]
                    vol_spike = live_vol / vol_ma20 if vol_ma20 > 0 else 0

                    hi52 = df_live["high"].astype(float).tail(252).max()
                    lo52 = df_live["low"].astype(float).tail(252).min()
                    pct52 = ((live_price - lo52) / (hi52 - lo52) * 100) if hi52 != lo52 else 50

                    chg_20d = ((live_price / c.iloc[-21] - 1) * 100) if len(c) > 20 else 0

                    macd_cross = "BULL" if macd_hist > 0 else "BEAR"
                    if macd_hist > 0 and macd_hist_prev <= 0:
                        macd_cross = "BUY"

                    row = {
                        "ticker": ticker_name,
                        "price": live_price,
                        "rsi_14": rsi,
                        "ema_trend": "UP" if ema9 > ema21 else "DOWN",
                        "long_trend": "BULL" if ema50 > ema200 else "BEAR",
                        "above_ma200": live_price > ema200,
                        "macd_cross": macd_cross,
                        "vol_spike": vol_spike,
                        "52w_pct": pct52,
                        "chg_20d_pct": chg_20d,
                    }

                    # Check mỗi preset
                    for pname, pcfg in PRESETS.items():
                        if pname == "value":
                            continue
                        try:
                            if pcfg["filter"] and pcfg["filter"](row):
                                live_hits[pname].append(row)
                        except Exception:
                            continue

                    scanned += 1
                except Exception:
                    continue

            # Render results
            total_hits_live = sum(len(v) for v in live_hits.values())
            st.markdown(
                f'<div style="background:#1e293b;padding:8px 14px;border-radius:6px;'
                f'margin:8px 0;font-size:13px;color:#94a3b8">'
                f'🔴 <b style="color:#ef4444">LIVE</b> — Scanned {scanned} mã '
                f'— {total_hits_live} tín hiệu real-time'
                f'</div>',
                unsafe_allow_html=True,
            )

            if total_hits_live > 0:
                # Show summary counts only — click expander for details
                _active_presets = [(p, h) for p, h in live_hits.items() if h]
                _summary = " | ".join(
                    f"{PRESET_ICONS.get(p, '')} {p} ({len(h)})"
                    for p, h in _active_presets
                )
                st.markdown(
                    f'<div style="font-size:12px;color:#94a3b8;margin:4px 0">{_summary}</div>',
                    unsafe_allow_html=True,
                )
                with st.expander("Xem chi tiết tín hiệu live", expanded=False):
                    cols = st.columns(min(4, len(_active_presets)))
                    col_idx = 0
                    for pname, hits in _active_presets:
                        icon = PRESET_ICONS.get(pname, "📊")
                        with cols[col_idx % len(cols)]:
                            st.markdown(f"**{icon} {pname}** ({len(hits)})")
                            for h in sorted(hits, key=lambda x: x.get("rsi_14", 50))[:5]:
                                _rsi = h.get("rsi_14", 0)
                                _vs = h.get("vol_spike", 0)
                                st.markdown(
                                    f"<span style='color:#60a5fa;font-size:12px'>{h['ticker']}</span>"
                                    f" <span style='color:#6b7280;font-size:10px'>"
                                    f"RSI {_rsi:.0f} Vol {_vs:.1f}x</span>",
                                    unsafe_allow_html=True,
                                )
                        col_idx += 1
            else:
                st.caption("Chưa có tín hiệu — chờ data accumulate...")

        _live_screener_fragment()

    # ── Alerts ─────────────────────────────────────────────────────────────
    _alerts = compute_alerts(gen_time)
    if _alerts:
        _new_alerts = [a for a in _alerts if a["type"] == "new"]
        _rem_alerts = [a for a in _alerts if a["type"] == "removed"]
        with st.expander(f"🔔 Alerts — {len(_new_alerts)} mã mới, {len(_rem_alerts)} mã ra ({gen_time[:10]})", expanded=False):
            _ac1, _ac2 = st.columns(2)
            with _ac1:
                if _new_alerts:
                    st.markdown("**🆕 Mới vào preset:**")
                    for a in _new_alerts[:20]:
                        icon = PRESET_ICONS.get(a["preset"], "")
                        st.markdown(f"- <span style='color:#10b981'>{a['ticker']}</span> → {icon} {a['preset']}", unsafe_allow_html=True)
                else:
                    st.caption("Không có mã mới vào preset")
            with _ac2:
                if _rem_alerts:
                    st.markdown("**❌ Ra khỏi preset:**")
                    for a in _rem_alerts[:20]:
                        icon = PRESET_ICONS.get(a["preset"], "")
                        st.markdown(f"- <span style='color:#ef4444'>{a['ticker']}</span> ← {icon} {a['preset']}", unsafe_allow_html=True)
                else:
                    st.caption("Không có mã nào ra khỏi preset")

    # Metric cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'''<div class="metric-card"><div class="label">Tổng mã theo dõi</div>
            <div class="value">{total_tickers:,}</div><div class="sub">trong warehouse</div></div>''', unsafe_allow_html=True)
    with c2:
        st.markdown(f'''<div class="metric-card"><div class="label">Đã phân loại ngành</div>
            <div class="value">{classified:,}</div><div class="sub">{classified/total_tickers*100:.0f}% tổng mã</div></div>''', unsafe_allow_html=True)
    with c3:
        st.markdown(f'''<div class="metric-card"><div class="label">Tổng tín hiệu</div>
            <div class="value">{total_hits:,}</div><div class="sub">qua {len(presets_data)} presets</div></div>''', unsafe_allow_html=True)
    with c4:
        top_count = top_preset[1].get("count", 0)
        icon = PRESET_ICONS.get(top_preset[0], "")
        st.markdown(f'''<div class="metric-card"><div class="label">Preset nhiều nhất</div>
            <div class="value">{icon} {top_count}</div><div class="sub">{top_preset[0]}</div></div>''', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Market Session Stats (4 time-window tables with 30-day history) ──
    with st.expander("📊 Thống kê giao dịch theo phiên (30 ngày)", expanded=False):
        @st.fragment(run_every=30)
        def _session_stats_fragment():
            try:
                # One-shot backfill per session: populates ~30 trading days of
                # history when the JSON file is missing or sparse. The runner
                # also backfills daily, so this is just for first-time / dev use.
                if not st.session_state.get("_session_stats_backfilled"):
                    try:
                        _backfill_session_stats()
                    except Exception:
                        pass
                    st.session_state["_session_stats_backfilled"] = True
                    load_session_stats_history.clear()

                # EOD reconciliation: replace yesterday's estimate with exact
                # value once the EOD batch posts in price_history. Cheap (~2s
                # for 4 indices); skip if last reconcile was <30 min ago to
                # avoid hammering the API on every fragment rerun.
                _now_ts = datetime.now().timestamp()
                _last_recon = st.session_state.get("_session_stats_last_recon", 0)
                if _now_ts - _last_recon > 1800:  # 30 minutes
                    try:
                        if _reconcile_eod() > 0:
                            load_session_stats_history.clear()
                    except Exception:
                        pass
                    st.session_state["_session_stats_last_recon"] = _now_ts

                # Load history + compute today
                history = load_session_stats_history()
                stats = compute_session_stats()
                has_data = any(
                    any(v.get("vol", 0) > 0 for v in ws.values())
                    for ws in stats.values()
                )
                if has_data:
                    save_session_stats(stats)

                # Radio toggle: total (matched + block deals) vs matched-only.
                # Matched-only excludes block-deal spikes so days with large
                # off-market deals don't appear inflated relative to neighbors
                # (the 9/3-10/3 case the user investigated).
                _mode_choice = st.radio(
                    "Loại GTGD hiển thị",
                    options=["Tổng", "Khớp lệnh"],
                    index=0,
                    horizontal=True,
                    key="_session_stats_gtgd_mode",
                    help=(
                        "Tổng = matched + block deals (thoả thuận). "
                        "Khớp lệnh = chỉ giao dịch khớp lệnh thường, "
                        "ổn định hơn cho so sánh giữa các ngày. "
                        "Cells thiếu data matched (hôm nay / UPCOM) tự "
                        "fallback về tổng."
                    ),
                )
                _mode = "matched" if _mode_choice == "Khớp lệnh" else "total"

                windows = list(SESSION_WINDOWS.keys())
                # Row 1: Bảng 1 + Bảng 2
                r1c1, r1c2 = st.columns(2)
                with r1c1:
                    render_session_stats_table(
                        windows[0], stats.get(windows[0], {}), history, mode=_mode)
                with r1c2:
                    render_session_stats_table(
                        windows[1], stats.get(windows[1], {}), history, mode=_mode)

                # Row 2: Bảng 3 + Bảng 4
                r2c1, r2c2 = st.columns(2)
                with r2c1:
                    render_session_stats_table(
                        windows[2], stats.get(windows[2], {}), history, mode=_mode)
                with r2c2:
                    render_session_stats_table(
                        windows[3], stats.get(windows[3], {}), history, mode=_mode)
            except Exception as e:
                st.warning(f"Không tải được thống kê phiên: {e}")

        _session_stats_fragment()

    if selected_preset and selected_preset in presets_data:
        preset_info = presets_data[selected_preset]
        icon = PRESET_ICONS.get(selected_preset, "📊")
        st.markdown(f"### {icon} {selected_preset.upper()}")
        st.caption(preset_info.get("desc", ""))

        df = df_from_preset(preset_info)
        if df.empty:
            st.info("Không có mã nào khớp với preset này.")
        else:
            if selected_industry != "Tất cả" and "Ngành" in df.columns:
                df = df[df["Ngành"] == selected_industry]

            raw_df = pd.DataFrame(presets_data[selected_preset]["results"])
            if not raw_df.empty and "ticker" in raw_df.columns:
                if "last_close" in raw_df.columns:
                    if price_min > 0: raw_df = raw_df[raw_df["last_close"].fillna(0) >= price_min]
                    if price_max > 0: raw_df = raw_df[raw_df["last_close"].fillna(0) <= price_max]
                if "chg_1d_pct" in raw_df.columns:
                    mask = raw_df["chg_1d_pct"].isna() | ((raw_df["chg_1d_pct"] >= chg1d_range[0]) & (raw_df["chg_1d_pct"] <= chg1d_range[1]))
                    raw_df = raw_df[mask]
                if "chg_5d_pct" in raw_df.columns:
                    mask = raw_df["chg_5d_pct"].isna() | ((raw_df["chg_5d_pct"] >= chg5d_range[0]) & (raw_df["chg_5d_pct"] <= chg5d_range[1]))
                    raw_df = raw_df[mask]
                if "chg_20d_pct" in raw_df.columns:
                    mask = raw_df["chg_20d_pct"].isna() | ((raw_df["chg_20d_pct"] >= chg20d_range[0]) & (raw_df["chg_20d_pct"] <= chg20d_range[1]))
                    raw_df = raw_df[mask]
                if vol_min > 0 and "vol_spike" in raw_df.columns:
                    raw_df = raw_df[raw_df["vol_spike"].fillna(0) >= vol_min]
                if selected_industry != "Tất cả" and "industry" in raw_df.columns:
                    raw_df = raw_df[raw_df["industry"] == selected_industry]
                filtered_tickers = set(raw_df["ticker"].tolist())
                if "Ticker" in df.columns:
                    df = df[df["Ticker"].isin(filtered_tickers)]

            # Watchlist filter
            if _filter_wl and _wl_tickers and "Ticker" in df.columns:
                df = df[df["Ticker"].isin(_wl_tickers)]

            if df.empty:
                st.info("Không có mã nào khớp với bộ lọc hiện tại.")
            else:
                st.caption(f"**{len(df)} mã** | top {min(top_n, len(df))} — Click tên cột để sắp xếp ↕ | Nhập mã vào sidebar để phân tích")
                render_table(df, top_n=top_n)

                csv = df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="⬇️ Export CSV", data=csv,
                    file_name=f"screen_{selected_preset}_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="scr_export_csv",
                )

    st.divider()
    st.markdown("### 📊 Tổng quan tất cả presets")
    overview_data = [{"Preset": f"{PRESET_ICONS.get(p,'')} {p}", "Mô tả": v.get("desc",""), "Số mã": v.get("count",0)}
                     for p, v in presets_data.items()]
    overview_df = pd.DataFrame(overview_data).sort_values("Số mã", ascending=False)
    st.dataframe(overview_df, width='stretch', hide_index=True, height=44 + len(overview_df)*36)


def _render_watchlist_sidebar(st, load_watchlist, save_watchlist, path) -> "tuple[list, bool]":
    """Khối ⭐ Watchlist ở sidebar → (mã đang theo dõi, bật lọc watchlist?).
    File hỏng ⇒ báo lỗi kèm đường dẫn + KHOÁ Thêm/Xoá (ghi lúc này = đè cả
    watchlist bằng [] + mã mới); không đụng tới file của user."""
    try:
        _wl_tickers, _broken = load_watchlist(), False
    except (OSError, ValueError) as e:
        _wl_tickers, _broken = [], True
        st.error(f"Không đọc được watchlist `{path}` ({e}). Đã khoá Thêm/Xoá để không ghi "
                 "đè — sửa hoặc khôi phục file rồi tải lại trang.")
    _filter_wl = st.toggle(f"Chỉ hiện Watchlist ({len(_wl_tickers)})", key="filter_watchlist")
    _wl_add = st.text_input("Thêm mã", placeholder="VCB, FPT, ...", key="wl_add_input").upper().strip()
    _wl_c1, _wl_c2 = st.columns(2)
    _new = None
    with _wl_c1:
        if st.button("➕ Thêm", key="wl_add_btn", use_container_width=True,
                     disabled=_broken) and _wl_add:
            _new = _wl_tickers + [t.strip() for t in _wl_add.replace(",", " ").split() if t.strip()]
    with _wl_c2:
        if st.button("🗑️ Xóa", key="wl_del_btn", use_container_width=True,
                     disabled=_broken) and _wl_add:
            del_tickers = {t.strip() for t in _wl_add.replace(",", " ").split() if t.strip()}
            _new = [t for t in _wl_tickers if t not in del_tickers]
    if _new is not None:
        try:
            save_watchlist(_new)
        except OSError as e:
            st.error(f"Không ghi được watchlist `{path}`: {e} — file trên đĩa giữ nguyên.")
        else:
            st.rerun()
    if _wl_tickers:
        st.caption("Đang theo dõi: " + ", ".join(_wl_tickers[:20]))
        if len(_wl_tickers) > 20:
            st.caption(f"... +{len(_wl_tickers)-20} mã khác")
    return _wl_tickers, _filter_wl
