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

import json
import os
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from vnstock_price_units import normalize_live_price, normalize_price_units


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
            quote_dir = Path("data_warehouse/_live")
            if not quote_dir.exists():
                st.caption("⏳ Chưa có quote data — bật Live Mode trước")
                return
            if not any(quote_dir.glob("quote_*.json")):
                st.caption("⏳ Chưa có quote data — chờ WSS poll...")
                return

            if "live_screener_state" not in st.session_state:
                st.session_state["live_screener_state"] = {}
            # Chỉ cổ phiếu thật (bỏ futures, index, warrant, CW, bond)
            scanned, live_hits, pending, errors = _scan_live_quotes(
                quote_dir, Path("data_warehouse/prices"),
                st.session_state["live_screener_state"], datetime.now().date(),
                lambda t: _is_stock(t) and t not in INDEX_SYMBOLS)

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
            if pending:
                st.caption(f"⏳ Mỗi lượt tính tối đa ~{_LIVE_BUDGET_S:g}s — còn {pending} mã "
                           f"chờ tính lượt sau")
            if errors:
                st.caption(f"⚠ {len(errors)} mã lỗi — vd {errors[0]}")

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
                            for _tk, _txt in _top_hits(hits):
                                st.markdown(
                                    f"<span style='color:#60a5fa;font-size:12px'>{_tk}</span>"
                                    f" <span style='color:#6b7280;font-size:10px'>{_txt}</span>",
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


# ── Live Scan: hàm thuần (test gọi được không cần Streamlit) ─────────────────

_OHLCV = ["time", "open", "high", "low", "close", "volume"]
_LIVE_MIN_BARS = 60          # = `min_rows` mặc định của `MarketScreener.scan` (EOD)
_LIVE_BUDGET_S = 1.0         # giây wall mỗi lượt cho việc đắt; fragment chạy trên luồng script
_DEFERRED = object()         # `_live_row` hết ngân sách: lượt sau tính tiếp


def _read_recent_history(ticker_dir: Path, years: int = 2, tail: int = 300) -> pd.DataFrame:
    """`tail` bar cuối của một mã, chỉ đọc `years` thư mục `year=` mới nhất (EOD lookback 300
    cũng chỉ đọc 2 năm). Trong năm đọc file theo mtime CŨ→MỚI rồi khử trùng ngày giữ bản MỚI:
    Dropbox có thể đẻ "(conflicted copy).parquet" — cùng ngữ nghĩa
    `vnstock_strategy._read_ticker_dir`."""
    import pyarrow.parquet as pq

    frames = [pq.read_table(str(pf), columns=_OHLCV).to_pandas()
              for yd in sorted(ticker_dir.glob("year=*"))[-years:]
              for pf in sorted(yd.glob("*.parquet"), key=lambda f: f.stat().st_mtime)]
    if not frames:
        return pd.DataFrame(columns=_OHLCV)
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    df = df.drop_duplicates("time", keep="last").sort_values("time").tail(tail)
    return normalize_price_units(df.reset_index(drop=True))


def _quote_day(quote: dict) -> pd.Timestamp | None:
    """Ngày phiên của quote theo giờ VN (không tz); `time` thiếu/hỏng ⇒ None."""
    try:
        t = pd.Timestamp(quote.get("time"))
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    if t.tz is not None:
        t = t.tz_convert("Asia/Ho_Chi_Minh").tz_localize(None)
    return t.normalize()


def _live_frame(hist: pd.DataFrame, quote: dict, today: date) -> pd.DataFrame | None:
    """`hist` + quote live của HÔM NAY. Quote ngày trước `today` ⇒ None dù trùng ngày bar cuối
    (chụp giữa phiên đã qua — đè bar EOD bằng giá 11:00 là tín hiệu giả; row EOD đã có ở bảng
    screener chính); cũ hơn bar cuối / giá hỏng ⇒ None. Còn lại: cùng ngày bar cuối ⇒ thay bar
    cuối, ngày sau ⇒ nối bar mới. Không sửa `hist` (nằm trong cache). `volume` của quote là
    TÍCH LUỸ cả phiên = KL bar ngày."""
    day = _quote_day(quote)
    try:
        price, vol = float(quote.get("price") or 0), float(quote.get("volume") or 0)
        q_high, q_low = float(quote.get("high") or 0), float(quote.get("low") or 0)
    except (TypeError, ValueError):
        return None
    last = hist.iloc[-1]
    last_day = last["time"].normalize()
    if price <= 0 or day is None or day < max(last_day, pd.Timestamp(today)):
        return None
    ref = float(last["close"])          # đơn vị giá live suy theo kho, không theo ngưỡng cứng
    price = normalize_live_price(ref, price)
    high = max(normalize_live_price(ref, q_high) if q_high > 0 else price, price)
    low = min(normalize_live_price(ref, q_low) if q_low > 0 else price, price)
    if day == last_day:
        base = hist.iloc[:-1]
        bar = {"time": last["time"], "open": last["open"], "high": max(last["high"], high),
               "low": min(last["low"], low), "close": price,
               "volume": vol if vol > 0 else last["volume"]}
    else:
        base = hist
        # ponytail: quote không có giá mở cửa ⇒ open = close hôm qua; trần: mẫu nến có gap
        # mở cửa đọc sai; nâng cấp: lấy open từ `_live/bars_<ngày>.parquet`.
        bar = {"time": day, "open": ref, "high": high, "low": low, "close": price, "volume": vol}
    return pd.concat([base, pd.DataFrame([bar])], ignore_index=True)


def _live_row(entry: os.DirEntry, ticker: str, prices_dir: Path, state: dict, today: date,
              calc: Callable[[pd.DataFrame], dict], deadline: float) -> dict | None | object:
    """Row chỉ báo live của một mã, ghi nhớ 2 tầng trong `state`: mtime file quote không đổi
    ⇒ khỏi mở file; đổi mtime mà (ngày, giá, KL, cao, thấp) như cũ ⇒ khỏi tính lại (tầng lạnh
    `vnstock_wss` ghi lại file mỗi COLD_EVERY_N vòng dù giá đứng yên). Ngoài hai ca rẻ đó,
    quá `deadline` (`time.monotonic`) ⇒ `_DEFERRED`, không ghi memo."""
    mtime = entry.stat().st_mtime_ns
    memo = state["rows"].get(ticker)
    if memo is not None and memo[0] == mtime:
        return memo[2]
    hists = state["hist"]
    if ticker in hists and hists[ticker] is None:   # đã biết thiếu/ngắn: rẻ, không tốn ngân sách
        return None
    # Đọc JSON vừa ghi cũng đắt: lần mở đầu sau khi ghi ~7ms/file (đo 17/10 ở thư mục tạm
    # trên desktop, lần sau 0,13ms) ⇒ 1.100 file tầng lạnh ghi lại = 11s wall dù CPU 0,4s.
    if time.monotonic() >= deadline:
        return _DEFERRED
    if ticker not in hists:             # thiếu thư mục / < 60 bar cũng nhớ (None), khỏi dò lại
        hist = _read_recent_history(prices_dir / f"ticker={ticker}")
        hists[ticker] = hist if len(hist) >= _LIVE_MIN_BARS else None
    if hists[ticker] is None:
        return None
    with open(entry.path, encoding="utf-8") as f:
        quote = json.load(f)
    if not isinstance(quote, dict):     # JSON hợp lệ sai dạng: nhớ để lượt sau khỏi mở lại
        state["rows"][ticker] = (mtime, None, None)
        return None
    key = (_quote_day(quote), *(quote.get(k) for k in ("price", "volume", "high", "low")))
    if memo is not None and memo[1] == key:
        row = memo[2]
    else:
        frame = _live_frame(hists[ticker], quote, today)
        ind = calc(frame) if frame is not None else {}
        row = {**ind, "ticker": ticker} if ind else None
    state["rows"][ticker] = (mtime, key, row)
    return row


def _scan_live_quotes(quote_dir: Path, prices_dir: Path, state: dict, today: date,
                      is_stock: Callable[[str], bool], budget_s: float = _LIVE_BUDGET_S,
                      ) -> tuple[int, dict[str, list[dict]], int, list[str]]:
    """Một lượt Live Scan ⇒ (số mã có row, preset → các row khớp, số mã chờ lượt sau,
    lỗi `"<MÃ>: <Lỗi>: <msg>"`).

    Chỉ dùng quote của `today` (`_live_frame`). `state` do caller giữ qua các lượt (fragment
    để trong `st.session_state`). Sang ngày mới thì xoá sạch: kho có bar mới sau pipeline
    18:00. Việc đắt chỉ làm trong `budget_s` giây; mã bị hoãn giữ row cũ (nếu có) và lượt sau
    bắt đầu từ mã hoãn đầu tiên, không thì mã cuối danh sách đói khi lượt nào cũng hết giờ.
    Mã lỗi bị bỏ, không ghi memo (lượt sau thử lại) nhưng được trả về để fragment báo."""
    from vnstock_screener import PRESETS, _calc_indicators   # lazy: module kéo `rich`

    if state.get("day") != today:
        state.clear()
        state.update(day=today, hist={}, rows={}, cursor="")
    hits: dict[str, list[dict]] = {p: [] for p in PRESETS if p != "value"}
    scanned, pending, errors, cursor = 0, 0, [], ""
    with os.scandir(quote_dir) as it:
        entries = [e for e in it if e.name.startswith("quote_") and e.name.endswith(".json")]
    entries.sort(key=lambda e: (e.name < state["cursor"], e.name))   # xoay về mã hoãn lượt trước
    deadline = time.monotonic() + budget_s
    for entry in entries:
        ticker = entry.name[len("quote_"):-len(".json")]
        if not is_stock(ticker):
            continue
        try:
            row = _live_row(entry, ticker, prices_dir, state, today, _calc_indicators, deadline)
        except Exception as e:          # file ghi dở, parquet hỏng, dữ liệu lạ: chỉ bỏ mã này
            errors.append(f"{ticker}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if row is _DEFERRED:
            pending += 1
            cursor = cursor or entry.name
            row = state["rows"].get(ticker, (None, None, None))[2]
        if row is None:
            continue
        scanned += 1
        for pname in hits:
            try:
                if PRESETS[pname]["filter"](row):
                    hits[pname].append(row)
            except TypeError:           # filter so số với None (vd rsi_14 None) ⇒ không khớp
                continue
    state["cursor"] = cursor
    return scanned, hits, pending, errors


def _top_hits(hits: list[dict], n: int = 5) -> list[tuple[str, str]]:
    """(mã, "RSI 28 Vol 1.6x") của `n` hit RSI thấp nhất; số thiếu (None) hiện "—"."""
    out = []
    for h in sorted(hits, key=lambda h: 50 if h.get("rsi_14") is None else h["rsi_14"])[:n]:
        rsi = "—" if h.get("rsi_14") is None else f"{h['rsi_14']:.0f}"
        vol = "—" if h.get("vol_spike") is None else f"{h['vol_spike']:.1f}x"
        out.append((h["ticker"], f"RSI {rsi} Vol {vol}"))
    return out
