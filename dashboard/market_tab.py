"""
Thị trường tab — 🌏 market-wide overview.

Shows VNINDEX / HNX / UPCOM / VN30 snapshots, breadth statistics,
sector flows and a commentary block. Extracted per the modularisation
plan in ``docs/REFACTOR_PLAN.md``.

Extraction notes
----------------
Streamlit is imported lazily so the module can be pulled into pytest
without the runtime. Dashboard-level helpers (``load_market_overview``,
``load_index_overview``, ``load_live_quote``, plus the
``VN30_SYMBOLS`` / ``INDEX_SYMBOLS`` / ``WSS_AVAILABLE`` constants) are
lazy-imported inside the render function. The four inline closures
(``_live_market_fragment``, ``_amp_color``, ``_dd_amp_color``,
``_build_commentary``) move with the block and stay inline inside
``render_market_tab``.
"""

from __future__ import annotations


def render_market_tab() -> None:
    """Render the Thị trường tab. Lazy imports Streamlit + dashboard helpers."""
    try:
        import streamlit as st
    except ImportError:
        print("[market_tab] streamlit not available")
        return

    import sys
    import json
    import numpy as np
    import pandas as pd
    from datetime import datetime, timedelta
    from pathlib import Path

    if 'vnstock_dashboard' not in sys.modules:
        _m = sys.modules.get('__main__') or sys.modules.get('main')
        if _m and hasattr(_m, 'WSS_AVAILABLE'):
            sys.modules['vnstock_dashboard'] = _m

    try:
        from vnstock_dashboard import (
            INDEX_SYMBOLS, VN30_SYMBOLS, WSS_AVAILABLE,
            load_index_overview, load_live_quote, load_market_overview,
            load_price_history,
        )
    except Exception:
        # Fallback khi vnstock_wss không load được — tab vẫn render được
        INDEX_SYMBOLS = []
        VN30_SYMBOLS = []
        WSS_AVAILABLE = False
        from vnstock_dashboard import (
            load_index_overview, load_live_quote, load_market_overview,
            load_price_history,
        )

    # ── Sparkline helpers ──────────────────────────────────────────────────
    def _sparkline_svg(values: list, width: int = 80, height: int = 28) -> str:
        """Render a list of floats as an inline SVG sparkline.
        Values are alpha (excess return vs VNINDEX) over 30 days.
        Green if ending positive, red if negative.
        """
        vals = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
        if len(vals) < 2:
            return '<span style="color:#4b5563;font-size:10px">—</span>'
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx != mn else 1.0
        n = len(vals)
        # zero line y (clipped to [2, h-2])
        zero_y = max(2, min(height - 2, height - (-mn / rng) * height))
        pts = [(round(i / (n - 1) * width), round(height - (v - mn) / rng * height))
               for i, v in enumerate(vals)]
        pt_str = " ".join(f"{x},{y}" for x, y in pts)
        last_val = vals[-1]
        lc = "#10b981" if last_val >= 0 else "#ef4444"
        fc = "#10b98122" if last_val >= 0 else "#ef444422"
        # Polygon fill from zero line
        fill_pts = ([(pts[0][0], int(zero_y))] + pts + [(pts[-1][0], int(zero_y))])
        fp_str = " ".join(f"{x},{y}" for x, y in fill_pts)
        last_disp = f"{last_val:+.1f}%"
        return (f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
                f'style="display:inline-block;vertical-align:middle;overflow:visible">'
                f'<polygon points="{fp_str}" fill="{fc}" stroke="none"/>'
                f'<polyline points="{pt_str}" fill="none" stroke="{lc}" stroke-width="1.5" stroke-linejoin="round"/>'
                f'<line x1="0" y1="{zero_y:.0f}" x2="{width}" y2="{zero_y:.0f}" '
                f'stroke="#4b5563" stroke-width="0.5" stroke-dasharray="3,3"/>'
                f'<text x="{width+2}" y="{height//2+4}" font-size="9" fill="{lc}" '
                f'font-family="IBM Plex Mono,monospace">{last_disp}</text>'
                f'</svg>')

    @st.cache_data(ttl=1800, show_spinner=False)
    def _sector_alpha_sparklines(sector_tickers_json: str, vnindex_json: str,
                                  n_days: int = 30) -> dict:
        """Compute daily alpha sparkline data for each sector.

        sector_tickers_json: JSON of {sector: [[ticker, cap], ...]} (top 3 by cap)
        vnindex_json: JSON of {date_iso: close_price}
        Returns {sector: [alpha_day_0, ..., alpha_day_n-1]} (ascending date order)
        """
        import json as _json
        sector_map = _json.loads(sector_tickers_json)
        vni_dict = _json.loads(vnindex_json)
        if not vni_dict or not sector_map:
            return {}
        dates = sorted(vni_dict.keys())[-n_days:]
        if len(dates) < 3:
            return {}
        vni_prices = [float(vni_dict[d]) for d in dates]
        vni_base = vni_prices[0]
        vni_cumret = [(p / vni_base - 1) * 100 for p in vni_prices]

        result = {}
        for sector, tickers_caps in sector_map.items():
            if not tickers_caps:
                continue
            ticker_data: dict = {}
            for ticker, cap in tickers_caps[:3]:
                try:
                    df = load_price_history(str(ticker), days=n_days + 15)
                    if df.empty or "close" not in df.columns:
                        continue
                    df["_d"] = df["time"].dt.date.astype(str)
                    d_close = df.groupby("_d")["close"].last()
                    ticker_data[ticker] = (d_close, float(cap))
                except Exception:
                    continue
            if not ticker_data:
                continue
            sector_cumret = []
            for date in dates:
                wsum, cap_sum = 0.0, 0.0
                for _tk, (d_close, cap) in ticker_data.items():
                    avail = d_close[d_close.index <= date]
                    if avail.empty:
                        continue
                    base_avail = d_close[d_close.index >= dates[0]]
                    if base_avail.empty:
                        continue
                    base = float(base_avail.iloc[0])
                    if base <= 0:
                        continue
                    ret = (float(avail.iloc[-1]) / base - 1) * 100
                    wsum += ret * cap
                    cap_sum += cap
                sector_cumret.append(wsum / cap_sum if cap_sum > 0 else 0.0)
            result[sector] = [round(s - v, 2) for s, v in zip(sector_cumret, vni_cumret)]
        return result

    col_title_m, col_ref_m = st.columns([6,1])
    with col_title_m:
        st.markdown("### 🌏 Tổng quan thị trường theo ngành")
    with col_ref_m:
        if st.button("🔄", key="market_refresh", help="Refresh"):
            st.cache_data.clear()
            st.rerun()

    # Data staleness badges — cảnh báo khi cache cũ
    try:
        from vnstock_freshness import render_freshness_row
        render_freshness_row([
            ("📊 Market overview", Path("data_warehouse/_meta/market_overview.json"), 24 * 3600),
            ("💸 NN flow",         Path("data_warehouse/_meta/nn_flow_cache.json"),    2 * 3600),
            ("⏱ Session stats",    Path("data_warehouse/_meta/market_session_stats.json"), 1 * 3600),
        ])
    except Exception:
        pass

    # ── Live Market Heatmap (VN30 real-time) ──────────────────────────────
    if st.session_state.get("live_mode") and WSS_AVAILABLE:
        @st.fragment(run_every=5)
        def _live_market_fragment():
            _vn30_quotes = []
            for _sym in VN30_SYMBOLS:
                _q = load_live_quote(_sym)
                if _q and float(_q.get("price", 0)) > 0:
                    _vn30_quotes.append(_q)

            if not _vn30_quotes:
                st.caption("⏳ Chờ WSS data...")
                return

            # Live Index quotes
            _idx_row = ""
            for _ix in INDEX_SYMBOLS[:4]:
                _iq = load_live_quote(_ix)
                if _iq and float(_iq.get("price", 0)) > 0:
                    _ip = float(_iq["price"])
                    _ichg = float(_iq.get("chg_pct", 0))
                    _ic = "#10b981" if _ichg >= 0 else "#ef4444"
                    _isign = "+" if _ichg >= 0 else ""
                    _idx_row += (
                        f"<div style='flex:1;text-align:center;padding:8px;'>"
                        f"<div style='color:#6b7280;font-size:10px;text-transform:uppercase'>{_ix}</div>"
                        f"<div style='color:#e5e7eb;font-size:18px;font-weight:700'>{_ip:,.2f}</div>"
                        f"<div style='color:{_ic};font-size:13px;font-weight:600'>{_isign}{_ichg:.2f}%</div>"
                        f"</div>"
                    )
            if _idx_row:
                st.markdown(
                    f"<div style='display:flex;gap:8px;margin-bottom:12px;background:#111827;"
                    f"border-radius:8px;padding:4px'>{_idx_row}</div>",
                    unsafe_allow_html=True,
                )

            # VN30 Heatmap
            st.markdown(
                "<div style='color:#6b7280;font-size:11px;margin-bottom:6px;"
                "text-transform:uppercase;letter-spacing:0.08em'>"
                "🔴 VN30 Heatmap — Real-time</div>",
                unsafe_allow_html=True,
            )
            _cells = ""
            _up = _down = _flat = 0
            for _q in sorted(_vn30_quotes, key=lambda x: float(x.get("chg_pct", 0)), reverse=True):
                _tk = _q.get("ticker", "?")
                _p = float(_q.get("price", 0))
                _chg = float(_q.get("chg_pct", 0))
                _vol = float(_q.get("volume", 0))

                if _chg > 0:
                    _up += 1
                elif _chg < 0:
                    _down += 1
                else:
                    _flat += 1

                # Color intensity by change magnitude
                _abs_chg = min(abs(_chg), 5)
                _intensity = int(_abs_chg / 5 * 180) + 40
                if _chg > 0:
                    _bg = f"rgba(16,185,129,{_intensity/255:.2f})"
                    _tc = "#e5e7eb"
                elif _chg < 0:
                    _bg = f"rgba(239,68,68,{_intensity/255:.2f})"
                    _tc = "#e5e7eb"
                else:
                    _bg = "rgba(75,85,99,0.3)"
                    _tc = "#9ca3af"

                _sign = "+" if _chg >= 0 else ""
                _cells += (
                    f"<div style='background:{_bg};border-radius:4px;padding:6px 4px;"
                    f"text-align:center;min-width:80px;flex:1'>"
                    f"<div style='color:{_tc};font-weight:700;font-size:12px'>{_tk}</div>"
                    f"<div style='color:{_tc};font-size:11px'>{_p:,.0f}</div>"
                    f"<div style='color:{_tc};font-size:10px;font-weight:600'>{_sign}{_chg:.2f}%</div>"
                    f"</div>"
                )

            st.markdown(
                f"<div style='display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px'>"
                f"{_cells}</div>",
                unsafe_allow_html=True,
            )

            # Mini breadth from live data
            _total = len(_vn30_quotes)
            st.markdown(
                f"<div style='color:#6b7280;font-size:11px;margin-bottom:12px'>"
                f"VN30: <span style='color:#10b981'>↑{_up}</span> "
                f"<span style='color:#9ca3af'>={_flat}</span> "
                f"<span style='color:#ef4444'>↓{_down}</span> "
                f"({_total} mã)"
                f"</div>",
                unsafe_allow_html=True,
            )

        _live_market_fragment()
        st.divider()

    # ── Chỉ số thị trường ────────────────────────────────────────────────────
    # Load 90 ngày một lần, reuse cho sparklines + quant analysis + commentary
    with st.spinner("Đang tải dữ liệu chỉ số..."):
        idx_df = load_index_overview(days=90)

    if not idx_df.empty:
        st.markdown("#### 📈 Diễn biến chỉ số thị trường (30 phiên)")
        _indices = ["VNINDEX", "VN30", "HNXINDEX", "HNX30"]
        _idx_avail = [i for i in _indices if i in idx_df.columns]

        # Tính min/max GTGD toàn bảng cho data bar scale
        _gtgd_cols = [f"{i}_gtgd" for i in _idx_avail if f"{i}_gtgd" in idx_df.columns]
        _all_gtgd = []
        for gc in _gtgd_cols:
            _all_gtgd.extend(idx_df[gc].dropna().abs().tolist())
        _gtgd_max = max(_all_gtgd) if _all_gtgd else 1

        # Build HTML table
        _th = ("background:#111827;color:#6b7280;font-size:10px;font-weight:500;"
               "text-transform:uppercase;letter-spacing:0.05em;padding:6px 8px;"
               "border-bottom:2px solid #1f2937;white-space:nowrap;text-align:center;"
               "font-family:'IBM Plex Sans',sans-serif;")
        _td = "padding:5px 8px;border-bottom:1px solid #1a2234;white-space:nowrap;font-size:11px;font-family:'IBM Plex Mono',monospace;"

        # Headers: Date | VNINDEX close %D GTGD | VN30 close %D GTGD | ...
        header_html = f'<th style="{_th}">Ngày</th>'
        for idx_name in _idx_avail:
            header_html += f'<th colspan="3" style="{_th};border-left:2px solid #1f2937">{idx_name}</th>'

        sub_header = f'<th style="{_th}"></th>'
        for _ in _idx_avail:
            sub_header += f'<th style="{_th};border-left:2px solid #1f2937;font-size:9px">Close</th>'
            sub_header += f'<th style="{_th};font-size:9px">%D</th>'
            sub_header += f'<th style="{_th};font-size:9px">GTGD (tỷ)</th>'

        rows_idx = []
        for i, (_, row) in enumerate(idx_df.head(20).iterrows()):
            bg = "#0d1117" if i % 2 == 0 else "#111827"
            date_str = pd.Timestamp(row["time"]).strftime("%Y-%m-%d")
            cells = f'<td style="{_td}color:#9ca3af">{date_str}</td>'

            for idx_name in _idx_avail:
                close_val = row.get(idx_name)
                chg_val = row.get(f"{idx_name}_chg")
                gtgd_val = row.get(f"{idx_name}_gtgd")

                # Close
                close_str = f"{close_val:,.2f}" if pd.notna(close_val) else "—"
                cells += f'<td style="{_td}color:#e5e7eb;text-align:right;border-left:2px solid #1f2937">{close_str}</td>'

                # %D with color
                if pd.notna(chg_val):
                    chg_color = "#10b981" if chg_val > 0 else ("#ef4444" if chg_val < 0 else "#9ca3af")
                    chg_str = f"+{chg_val:.1f}%" if chg_val > 0 else f"{chg_val:.1f}%"
                    cells += f'<td style="{_td}color:{chg_color};text-align:right">{chg_str}</td>'
                else:
                    cells += f'<td style="{_td}color:#4b5563;text-align:right">—</td>'

                # GTGD data bar
                if pd.notna(gtgd_val):
                    bar_pct = min(100, int(abs(gtgd_val) / _gtgd_max * 100))
                    bar_color = "#10b981" if pd.notna(chg_val) and chg_val >= 0 else "#ef4444"
                    gtgd_str = f"{gtgd_val:,.0f}"
                    cells += (
                        f'<td style="{_td}padding:3px 6px;min-width:100px">'
                        f'<div style="display:flex;align-items:center;gap:4px;justify-content:flex-end">'
                        f'<span style="color:#6b7280;font-size:10px">{gtgd_str}</span>'
                        f'<div style="width:50px;height:12px;background:#1a2234;border-radius:2px;overflow:hidden">'
                        f'<div style="width:{bar_pct}%;height:100%;background:{bar_color};border-radius:2px"></div>'
                        f'</div></div></td>'
                    )
                else:
                    cells += f'<td style="{_td}color:#4b5563;text-align:right">—</td>'

            rows_idx.append(f'<tr style="background:{bg}">{cells}</tr>')

        idx_tbl = f"""<div style="overflow-x:auto;border-radius:8px;border:1px solid #1f2937;background:#0d1117;max-height:500px;overflow-y:auto">
    <table style="width:100%;border-collapse:collapse">
    <thead><tr>{header_html}</tr><tr>{sub_header}</tr></thead>
    <tbody>{"".join(rows_idx)}</tbody>
    </table></div>"""
        st.markdown(idx_tbl, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    # ── Load tất cả dữ liệu thị trường (1 lần duy nhất) ─────────────────────
    with st.spinner("Đang tổng hợp dữ liệu thị trường..."):
        mkt_df = load_market_overview()
    breadth = st.session_state.get("_mkt_breadth", {})

    if breadth:
        st.markdown("#### 📊 Breadth Indicators — Sức khỏe thị trường")
        b1, b2, b3, b4, b5 = st.columns(5)

        pct_ma200 = breadth["above_ma200_pct"]
        ma200_color = "#10b981" if pct_ma200 > 50 else ("#f59e0b" if pct_ma200 > 30 else "#ef4444")
        with b1:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">Trên MA200</div>'
                f'<div class="value" style="color:{ma200_color}">{pct_ma200:.1f}%</div>'
                f'<div class="sub">{breadth["above_ma200"]}/{breadth["total"]} mã</div>'
                f'</div>', unsafe_allow_html=True)

        with b2:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">RSI &lt; 30 (Quá bán)</div>'
                f'<div class="value" style="color:#10b981">{breadth["rsi_oversold_pct"]:.1f}%</div>'
                f'<div class="sub">{breadth["rsi_oversold"]} mã oversold</div>'
                f'</div>', unsafe_allow_html=True)

        with b3:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">RSI &gt; 70 (Quá mua)</div>'
                f'<div class="value" style="color:#ef4444">{breadth["rsi_overbought_pct"]:.1f}%</div>'
                f'<div class="sub">{breadth["rsi_overbought"]} mã overbought</div>'
                f'</div>', unsafe_allow_html=True)

        ad = breadth["ad_ratio"]
        ad_color = "#10b981" if ad > 1 else ("#ef4444" if ad < 1 else "#9ca3af")
        with b4:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">A/D Ratio</div>'
                f'<div class="value" style="color:{ad_color}">{ad:.2f}</div>'
                f'<div class="sub">↑{breadth["advances"]} ↓{breadth["declines"]} ={breadth["unchanged"]}</div>'
                f'</div>', unsafe_allow_html=True)

        nnh = breadth["net_new_highs"]
        nnh_color = "#10b981" if nnh > 0 else ("#ef4444" if nnh < 0 else "#9ca3af")
        with b5:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="label">Net New Highs</div>'
                f'<div class="value" style="color:{nnh_color}">{nnh:+d}</div>'
                f'<div class="sub">↑{breadth["new_highs"]} đỉnh · ↓{breadth["new_lows"]} đáy 52W</div>'
                f'</div>', unsafe_allow_html=True)

        # ── Progress bars ─────────────────────────────────────────────────────
        pb1, pb2, pb3 = st.columns(3)
        with pb1:
            st.caption("% Trên MA200")
            st.progress(min(pct_ma200 / 100, 1.0))
        with pb2:
            adv_pct = breadth["advances"] / max(breadth["total"], 1)
            st.caption(f"Advance/Decline ({breadth['advances']}/{breadth['declines']})")
            st.progress(min(adv_pct, 1.0))
        with pb3:
            rsi_neutral = 100 - breadth["rsi_oversold_pct"] - breadth["rsi_overbought_pct"]
            st.caption(f"RSI: 🟢{breadth['rsi_oversold_pct']:.0f}% · ⚪{rsi_neutral:.0f}% · 🔴{breadth['rsi_overbought_pct']:.0f}%")
            st.progress(min(rsi_neutral / 100, 1.0))

        st.divider()

    # ── F5: Market regime detector ───────────────────────────────────────────
    try:
        import vnstock_regime as _reg
        _regime_data = _reg.load_regime()
        _r = _regime_data

        with st.container():
            _rc1, _rc2, _rc3 = st.columns([2, 3, 3])

            with _rc1:
                st.markdown(
                    f'<div style="background:{_r["bg"]};border:1px solid {_r["color"]}33;'
                    f'border-radius:8px;padding:12px 16px;text-align:center">'
                    f'<div style="font-size:22px;font-weight:700;color:{_r["color"]}">'
                    f'{_r["label"]}</div>'
                    f'<div style="color:#9ca3af;font-size:12px;margin-top:4px">'
                    f'Score: {_r["score"]:+d}/{_r["n_signals"]} · '
                    f'Conviction: {_r["confidence"]*100:.0f}%</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            with _rc2:
                st.caption("**📡 Tín hiệu**")
                _dir_icon = {1: "🟢", -1: "🔴", 0: "⚪"}
                for sig in _r["signals"]:
                    icon = _dir_icon.get(sig["direction"], "⚪")
                    st.markdown(
                        f'{icon} **{sig["name"]}**: {sig["value"]}'
                        f'<span style="color:#6b7280;font-size:11px"> — {sig["detail"]}</span>',
                        unsafe_allow_html=True,
                    )

            with _rc3:
                st.caption("**🎯 Screener preset gợi ý**")
                _presets = _r["suggested_presets"]
                if _presets:
                    for p in _presets:
                        label = _reg.PRESET_DISPLAY.get(p, p)
                        st.markdown(
                            f'<span style="background:#1e3a5f;color:#60a5fa;'
                            f'padding:3px 10px;border-radius:12px;font-size:13px;'
                            f'display:inline-block;margin:2px">{label}</span>',
                            unsafe_allow_html=True,
                        )
                    st.caption(
                        "💡 Vào tab **Screener** → chọn preset trên để lọc "
                        "cổ phiếu phù hợp với regime hiện tại."
                    )
                else:
                    st.caption("Không có gợi ý cho regime này.")

        st.divider()
    except Exception:
        pass   # regime block is optional; never crash the tab

    # ── Market Overview theo ngành (dữ liệu đã load ở trên) ─────────────────
    if mkt_df.empty:
        st.warning("Không có dữ liệu.")
    else:
        # ── Metric cards ───────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        total_sectors = len(mkt_df)
        total_mktcap  = mkt_df["Vốn hoá (tỷ)"].sum() if "Vốn hoá (tỷ)" in mkt_df.columns else 0
        total_vol20   = mkt_df["Vol Avg 20"].sum()
        top_sector    = str(mkt_df.iloc[0]["Ngành"])

        with c1:
            st.markdown(f'<div class="metric-card"><div class="label">Số ngành</div><div class="value">{total_sectors}</div><div class="sub">đã phân loại</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><div class="label">Tổng vốn hoá</div><div class="value">{total_mktcap/1000:,.0f} nghìn tỷ</div><div class="sub">VND</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card"><div class="label">KLGD TB 20 ngày</div><div class="value">{total_vol20:,.0f}M</div><div class="sub">triệu cổ phiếu</div></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="metric-card"><div class="label">Ngành KLGD cao nhất</div><div class="value">{top_sector[:14]}</div><div class="sub">Vol 20: {float(mkt_df.iloc[0]["Vol Avg 20"]):.0f}M cp</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Drill-down + Sort controls ────────────────────────────────────────
        _ctrl1, _ctrl2, _ctrl3 = st.columns([4, 2, 1])
        _nganh_list = ["Tổng quan theo ngành"] + mkt_df["Ngành"].tolist()
        with _ctrl1:
            _selected_nganh = st.selectbox(
                "Ngành", _nganh_list, key="mkt_drill_industry",
                label_visibility="collapsed",
                placeholder="🔍 Click chọn ngành để drill-down..."
            )
        _sort_cols = ["Composite","Vốn hoá (tỷ)","GTGD TB (tỷ)","Vol Avg 20","Vol 5/20 %",
                      "Net BS 1T","Net BS 1M","Net BS 3M","Net BS 6M",
                      "NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)",
                      "Biên 1T (%)","Biên 1M (%)","Biên 3M (%)",
                      "Giá 1T %","Giá 1M %","Giá 3M %"]
        with _ctrl2:
            _sort_by = st.selectbox("Sắp xếp", _sort_cols, key="mkt_sort_col", label_visibility="collapsed")
        with _ctrl3:
            _sort_dir = st.selectbox("↕", ["↓ Giảm","↑ Tăng"], key="mkt_sort_dir", label_visibility="collapsed")
        _sort_asc = (_sort_dir == "↑ Tăng")

        # ── Bảng tổng hợp (ẩn khi drill-down) ─────────────────────────────────
        has_foreign = "NN 1T (tỷ)" in mkt_df.columns and mkt_df["NN 1T (tỷ)"].notna().any()
        _show_sector_table = (_selected_nganh == "Tổng quan theo ngành")

        # ── Color scale cho Biên độ (tương quan giữa ngành + khung thời gian) ──
        _amp_cols = ["Biên 1T (%)","Biên 1M (%)","Biên 3M (%)"]
        _amp_all_vals = []
        for _ac in _amp_cols:
            if _ac in mkt_df.columns:
                _amp_all_vals.extend(mkt_df[_ac].dropna().tolist())
        _amp_min = min(_amp_all_vals) if _amp_all_vals else 0
        _amp_max = max(_amp_all_vals) if _amp_all_vals else 1
        _amp_range = _amp_max - _amp_min if _amp_max > _amp_min else 1

        def _amp_color(val):
            """Map biên độ → gradient xanh lá (thấp) → vàng (TB) → đỏ (cao)."""
            t = (float(val) - _amp_min) / _amp_range  # 0..1
            t = max(0, min(1, t))
            if t < 0.5:
                # xanh lá → vàng
                r = int(16 + (245 - 16) * (t / 0.5))
                g = int(185 + (158 - 185) * (t / 0.5))
                b = int(129 + (11 - 129) * (t / 0.5))
            else:
                # vàng → đỏ
                r = int(245 + (239 - 245) * ((t - 0.5) / 0.5))
                g = int(158 + (68 - 158) * ((t - 0.5) / 0.5))
                b = int(11 + (68 - 11) * ((t - 0.5) / 0.5))
            return f"rgb({r},{g},{b})"

        _net_bs_cols = ("Net BS 1T","Net BS 1M","Net BS 3M","Net BS 6M")
        _nn_cols     = ("NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)")
        _avg_vol_cols = ("AVG 5-10 %","AVG 10-20 %")
        _free_vol_cols = ("Vol 5/Free %","Vol 10/Free %","Vol 20/Free %")

        # Heatmap scale cho Vol X/Free % — dùng chung cho sector + drill-down
        _fvol_all_vals = []
        for _fc in _free_vol_cols:
            if _fc in mkt_df.columns:
                _fvol_all_vals.extend(v for v in mkt_df[_fc].dropna().tolist()
                                      if isinstance(v, (int, float)) and not np.isnan(v))
        _fvol_min = min(_fvol_all_vals) if _fvol_all_vals else 0
        _fvol_max = max(_fvol_all_vals) if _fvol_all_vals else 1
        _fvol_rng = _fvol_max - _fvol_min if _fvol_max > _fvol_min else 1

        def _fvol_colors(val, fmin=None, frng=None):
            """(bg, text) — gradient vàng nhạt → cam → đỏ theo tỷ lệ vol/freefloat."""
            mn = fmin if fmin is not None else _fvol_min
            rn = frng if frng is not None else _fvol_rng
            t = max(0, min(1, (float(val) - mn) / rn))
            if t < 0.5:
                s = t / 0.5
                r = int(254 + (249 - 254) * s)
                g = int(252 + (115 - 252) * s)
                b = int(232 + (22  - 232) * s)
            else:
                s = (t - 0.5) / 0.5
                r = int(249 + (153 - 249) * s)
                g = int(115 + (27  - 115) * s)
                b = int(22  + (27  -  22) * s)
            bg   = f"rgb({r},{g},{b})"
            text = "#111827" if t < 0.35 else "#ffffff"
            return bg, text

        def color_val(val, col):
            """Trả về màu CSS theo giá trị."""
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return "#4b5563"
            if col in ("Giá 1T %","Giá 1M %","Giá 3M %") + _nn_cols + _net_bs_cols + _avg_vol_cols:
                return "#10b981" if float(val) > 0 else ("#ef4444" if float(val) < 0 else "#9ca3af")
            if col in _free_vol_cols:
                return "#e5e7eb"  # overridden by cell-level heatmap rendering
            if col == "Vol 5/20 %":
                v = float(val)
                return "#10b981" if v > 110 else ("#ef4444" if v < 90 else "#e5e7eb")
            if col in _amp_cols:
                return _amp_color(val)
            return "#e5e7eb"

        def fmt(val, col):
            if val is None:
                return "—"
            if isinstance(val, str):
                return val  # cột text như Ngành — trả về nguyên
            try:
                if np.isnan(float(val)):
                    return "—"
            except Exception:
                return str(val)
            v = float(val)
            if col in ("Giá 1T %","Giá 1M %","Giá 3M %"):
                return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
            if col in _nn_cols:
                return f"+{v:,.1f}" if v > 0 else f"{v:,.1f}"
            if col in _net_bs_cols:
                return f"+{v:,.1f}M" if v > 0 else f"{v:,.1f}M"
            if col in ("Vol Avg 5","Vol Avg 10","Vol Avg 20"):
                return f"{v:,.1f}M"
            if col in ("AVG 5-10 %","AVG 10-20 %"):
                return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
            if col in ("Vol 5/Free %","Vol 10/Free %","Vol 20/Free %"):
                return f"{v:.2f}%"
            if col == "Vol 5/20 %":
                return f"{v:.0f}%"
            if col in ("Vốn hoá (tỷ)","GTGD TB (tỷ)","Freefloat (tỷ)"):
                return f"{v:,.0f}"
            if col in ("Biên 1T (%)","Biên 1M (%)","Biên 3M (%)"):
                return f"{v:.1f}%"
            return str(int(v)) if v == int(v) else f"{v:.1f}"

        # Chọn cột hiển thị
        display_cols = ["Ngành","Số mã","Vốn hoá (tỷ)","Freefloat (tỷ)","GTGD TB (tỷ)",
                        "Vol Avg 5","Vol Avg 10","Vol Avg 20",
                        "AVG 5-10 %","AVG 10-20 %",
                        "Vol 5/Free %","Vol 10/Free %","Vol 20/Free %",
                        "Vol 5/20 %",
                        "Net BS 1T","Net BS 1M","Net BS 3M","Net BS 6M",
                        "NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)",
                        "Biên 1T (%)","Biên 1M (%)","Biên 3M (%)",
                        "Giá 1T %","Giá 1M %","Giá 3M %"]

        avail_cols = [c for c in display_cols if c in mkt_df.columns]

        # Build shared styles
        th_style = ("background:#111827;color:#6b7280;font-size:10px;font-weight:500;"
                    "text-transform:uppercase;letter-spacing:0.05em;padding:8px 10px;"
                    "border-bottom:2px solid #1f2937;white-space:nowrap;font-family:'IBM Plex Sans',sans-serif;")
        td_base   = "padding:7px 10px;border-bottom:1px solid #1a2234;white-space:nowrap;font-size:12px;font-family:'IBM Plex Mono',monospace;"

        if _show_sector_table:
            # ── Sparkline alpha history (30d) per sector ──────────────────────
            _sparklines: dict = {}
            try:
                import json as _json
                _tick_data_spark = st.session_state.get("_mkt_ticker_data")
                _idx_long_spark = idx_df  # reuse already-loaded 90d data
                if (_tick_data_spark is not None and not _tick_data_spark.empty
                        and _idx_long_spark is not None and not _idx_long_spark.empty
                        and "Ngành" in _tick_data_spark.columns
                        and "Vốn hoá (tỷ)" in _tick_data_spark.columns
                        and "VNINDEX" in _idx_long_spark.columns):
                    # Build sector → top 3 tickers by cap
                    _sec_tickers: dict = {}
                    for _sname, _grp in _tick_data_spark.groupby("Ngành"):
                        _sorted_grp = _grp.sort_values("Vốn hoá (tỷ)", ascending=False)
                        _sec_tickers[_sname] = [
                            [str(r["Mã"]), float(r["Vốn hoá (tỷ)"])]
                            for _, r in _sorted_grp.head(3).iterrows()
                            if r.get("Mã") and r.get("Vốn hoá (tỷ)")
                        ]
                    # Build VNINDEX close dict (date → close)
                    _vni_col = _idx_long_spark[["VNINDEX"]].copy()
                    if hasattr(_idx_long_spark.index, "strftime"):
                        _vni_col["_d"] = _idx_long_spark.index.strftime("%Y-%m-%d")
                    elif "time" in _idx_long_spark.columns:
                        _vni_col["_d"] = pd.to_datetime(_idx_long_spark["time"]).dt.date.astype(str)
                    else:
                        _vni_col = _vni_col.reset_index()
                        _vni_col["_d"] = pd.to_datetime(_vni_col.iloc[:, 0]).dt.date.astype(str)
                    _vni_close = _vni_col.dropna(subset=["VNINDEX"]).set_index("_d")["VNINDEX"]
                    _vni_close = _vni_close[~_vni_close.index.duplicated(keep="last")]
                    _vni_dict = {k: float(v) for k, v in _vni_close.items()}
                    if _sec_tickers and _vni_dict:
                        _sparklines = _sector_alpha_sparklines(
                            _json.dumps(_sec_tickers),
                            _json.dumps(_vni_dict),
                            n_days=30,
                        )
            except Exception:
                _sparklines = {}

            # ── Bảng ngành (sorted) ───────────────────────────────────────────
            _has_sparklines = bool(_sparklines)
            if _sort_by in mkt_df.columns:
                mkt_df = mkt_df.sort_values(_sort_by, ascending=_sort_asc, na_position="last").reset_index(drop=True)
            rows_html = []
            for i, (_, row) in enumerate(mkt_df.iterrows()):
                bg = "#0d1117" if i%2==0 else "#111827"
                cells = []
                # Sparkline cell (before other columns)
                if _has_sparklines:
                    _sec_name = row.get("Ngành", "")
                    _spark_vals = _sparklines.get(_sec_name, [])
                    _spark_svg = _sparkline_svg(_spark_vals)
                    cells.append(
                        f'<td style="{td_base}padding:4px 8px;min-width:140px;text-align:left">'
                        f'{_spark_svg}</td>')
                for col in avail_cols:
                    val = row.get(col)
                    display = fmt(val, col)
                    color   = color_val(val, col)
                    if col == "Ngành":
                        cells.append(f'<td style="{td_base}color:#a78bfa;font-weight:600;font-family:IBM Plex Sans,sans-serif">{display}</td>')
                    elif col == "Số mã":
                        cells.append(f'<td style="{td_base}color:#6b7280;text-align:center">{display}</td>')
                    elif col in _amp_cols and val is not None and not (isinstance(val, float) and np.isnan(val)):
                        t = (float(val) - _amp_min) / _amp_range
                        t = max(0, min(1, t))
                        bar_w = max(4, int(t * 100))
                        bar_color = _amp_color(val)
                        cells.append(
                            f'<td style="{td_base}padding:4px 6px;min-width:90px">'
                            f'<div style="display:flex;align-items:center;gap:5px;justify-content:flex-end">'
                            f'<span style="color:#9ca3af;font-size:11px">{display}</span>'
                            f'<div style="width:60px;height:14px;background:#1a2234;border-radius:2px;overflow:hidden">'
                            f'<div style="width:{bar_w}%;height:100%;background:{bar_color};border-radius:2px"></div>'
                            f'</div></div></td>')
                    elif col in _free_vol_cols and val is not None and not (isinstance(val, float) and np.isnan(val)):
                        bg_c, txt_c = _fvol_colors(val)
                        cells.append(f'<td style="{td_base}background:{bg_c};color:{txt_c};text-align:right;border-radius:3px;font-weight:500">{display}</td>')
                    else:
                        align = "right" if col != "Ngành" else "left"
                        cells.append(f'<td style="{td_base}color:{color};text-align:{align}">{display}</td>')
                rows_html.append(f'<tr style="background:{bg}">' + "".join(cells) + "</tr>")

            _spark_header = (f'<th style="{th_style}min-width:140px">α 30d vs VNINDEX</th>'
                             if _has_sparklines else "")
            headers = _spark_header + "".join(f'<th style="{th_style}">{c}</th>' for c in avail_cols)
            tbl_height = min(700, 52 + len(mkt_df)*36)
            html_tbl = f"""<div style="overflow-x:auto;border-radius:8px;border:1px solid #1f2937;background:#0d1117;max-height:{tbl_height}px;overflow-y:auto">
    <table style="width:100%;border-collapse:collapse">
    <thead><tr>{headers}</tr></thead>
    <tbody>{"".join(rows_html)}</tbody>
    </table></div>"""

            st.markdown(html_tbl, unsafe_allow_html=True)

            csv = mkt_df[avail_cols].to_csv(index=False, encoding="utf-8-sig")
            st.download_button("⬇️ Export CSV", data=csv,
                               file_name=f"market_overview_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                               mime="text/csv", key="mkt_export_csv")

            if not has_foreign:
                st.caption("⚠️ Dữ liệu dòng ngoại (NN) chưa có — cần vnstock API `Trading.foreign_trade()`. "
                           "Vốn hoá là ước tính từ giá × cổ phiếu lưu hành. Freefloat từ dữ liệu cổ đông lớn (KBS).")

        # ── Drill-down: chi tiết công ty theo ngành ───────────────────────────
        if _selected_nganh != "Tổng quan theo ngành":
            tick_data = st.session_state.get("_mkt_ticker_data")
            if tick_data is not None and not tick_data.empty:
                sector_df = tick_data[tick_data["Ngành"] == _selected_nganh].copy()
                if not sector_df.empty:
                    st.markdown(f"#### 🏢 Chi tiết ngành: {_selected_nganh} ({len(sector_df)} mã)")

                    # ── Quant analysis cho riêng ngành ──────────────────
                    _sec_scores = None  # populated inside try; used below for sort+export
                    try:
                        from vnstock_market_analyzer import (
                            compute_scores as _cs, rank as _rk, format_row as _fr,
                            build_preset_sets as _bps,
                            _sector_technical_summary as _sts,
                            compute_index_returns as _cir,
                            load_quarantine_tickers as _lqt,
                            load_recent_exdiv as _lred,
                        )
                        # Load screener presets
                        try:
                            from vnstock_dashboard import load_screener_results as _lsr
                            _presets = _bps(_lsr())
                        except Exception:
                            _presets = None
                        # Index returns for alpha computation
                        _dd_idx_ret = None
                        try:
                            _idx_long_dd = idx_df  # reuse already-loaded 90d data
                            if _idx_long_dd is not None and not _idx_long_dd.empty:
                                _dd_idx_ret = _cir(_idx_long_dd, index_col="VNINDEX")
                        except Exception:
                            pass
                        # Quarantine + ex-div filters
                        _quarantined = _lqt()
                        _exdiv = _lred(days_back=7)

                        _sec_scores = _cs(sector_df, presets=_presets,
                                          index_returns=_dd_idx_ret, exdiv_map=_exdiv)
                        if not _sec_scores.empty:
                            _sec_ranked = _rk(sector_df, _sec_scores, n_top=3, n_bot=3,
                                              name_col="Mã", quarantined=_quarantined)
                            _sec_comp_avg = float(_sec_scores["composite"].mean())
                            _sec_verdict = ("🔥 Dòng tiền mạnh" if _sec_comp_avg > 0.5
                                            else "📈 Tích cực" if _sec_comp_avg > 0.1
                                            else "⚖️ Trung tính" if abs(_sec_comp_avg) <= 0.1
                                            else "📉 Yếu" if _sec_comp_avg > -0.5
                                            else "❄️ Rất yếu")
                            _tech_summary = _sts(sector_df, _presets) if _presets else ""
                            _vr_badge = ""
                            if "_vol_regime" in _sec_scores.columns:
                                _vr = _sec_scores["_vol_regime"].mode()
                                if not _vr.empty and _vr.iloc[0] == "high":
                                    _vr_badge = " · ⚡ High-vol"

                            _exp_title = (f"🧠 Quant view · **{_selected_nganh}** · "
                                          f"Composite TB `{_sec_comp_avg:+.2f}` · {_sec_verdict}{_vr_badge}")
                            if _tech_summary:
                                _exp_title += f" · {_tech_summary}"
                            with st.expander(_exp_title, expanded=True):
                                # ── Controls row ───────────────────────────────
                                _ctrl_a, _ctrl_b = st.columns([3, 1])
                                with _ctrl_a:
                                    _show_detail = st.checkbox(
                                        "🔍 Hiển thị chi tiết (catalysts & red flags)",
                                        key=f"quant_detail_{_selected_nganh}", value=True)
                                with _ctrl_b:
                                    # Export buttons (inline)
                                    try:
                                        from vnstock_market_analyzer import (
                                            scores_to_export_df as _s2df,
                                            scores_to_markdown as _s2md,
                                        )
                                        _exp_df = _s2df(sector_df, _sec_scores, name_col="Mã")
                                        _exp_csv = _exp_df.to_csv(index=False, encoding="utf-8-sig")
                                        st.download_button(
                                            "⬇️ CSV", data=_exp_csv,
                                            file_name=f"quant_{_selected_nganh}_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                                            mime="text/csv",
                                            key=f"quant_csv_{_selected_nganh}",
                                            help="Export quant scores as CSV",
                                        )
                                    except Exception:
                                        pass

                                q_col1, q_col2 = st.columns(2)
                                with q_col1:
                                    st.markdown("**🎯 Top picks trong ngành**")
                                    _t_lines = []
                                    for r in _sec_ranked["top"]:
                                        if r.get("composite", 0) <= 0:
                                            break
                                        for ln in _fr(r, name_col="Mã", show_detail=_show_detail):
                                            _t_lines.append(ln if ln.startswith("  ") else f"- {ln}")
                                    st.markdown("\n".join(_t_lines) if _t_lines
                                                else "_Không có mã nào có composite dương._")
                                with q_col2:
                                    st.markdown("**⛔ Nên tránh**")
                                    _a_lines = []
                                    for r in _sec_ranked["avoid"]:
                                        if r.get("composite", 0) >= 0:
                                            break
                                        for ln in _fr(r, name_col="Mã", show_detail=_show_detail):
                                            _a_lines.append(ln if ln.startswith("  ") else f"- {ln}")
                                    st.markdown("\n".join(_a_lines) if _a_lines
                                                else "_Không có mã nào có composite âm._")

                                if _sec_ranked.get("rotation"):
                                    st.markdown("**🔄 Rotation signal (warming up)**")
                                    _rot_lines = []
                                    for r in _sec_ranked["rotation"]:
                                        for ln in _fr(r, name_col="Mã", show_detail=_show_detail):
                                            _rot_lines.append(ln if ln.startswith("  ") else f"- {ln}")
                                    st.markdown("\n".join(_rot_lines))

                                if _sec_ranked["stealth"]:
                                    st.markdown("**🕵️ Stealth / tích luỹ**")
                                    _s_lines = []
                                    for r in _sec_ranked["stealth"]:
                                        for ln in _fr(r, name_col="Mã", show_detail=_show_detail):
                                            _s_lines.append(ln if ln.startswith("  ") else f"- {ln}")
                                    st.markdown("\n".join(_s_lines))

                                if _sec_ranked["distribution"]:
                                    st.markdown("**⚠️ Distribution (giá xanh, tiền thoát)**")
                                    _d_lines = []
                                    for r in _sec_ranked["distribution"]:
                                        for ln in _fr(r, name_col="Mã", show_detail=_show_detail):
                                            _d_lines.append(ln if ln.startswith("  ") else f"- {ln}")
                                    st.markdown("\n".join(_d_lines))

                                if _quarantined:
                                    _quar_in_sector = _quarantined & set(
                                        sector_df.get("Mã", pd.Series()).dropna().str.upper().tolist()
                                    )
                                    if _quar_in_sector:
                                        st.caption(f"⚠️ Đã loại khỏi top picks do dữ liệu lỗi: "
                                                   f"`{'`, `'.join(sorted(_quar_in_sector))}`")

                                # Markdown export (inside expander, below rankings)
                                try:
                                    from vnstock_market_analyzer import scores_to_markdown as _s2md
                                    _md_text = _s2md(sector_df, _sec_scores,
                                                     name_col="Mã",
                                                     title=f"Quant Analysis — {_selected_nganh}")
                                    st.download_button(
                                        "⬇️ Markdown", data=_md_text.encode("utf-8"),
                                        file_name=f"quant_{_selected_nganh}_{pd.Timestamp.now().strftime('%Y%m%d')}.md",
                                        mime="text/markdown",
                                        key=f"quant_md_{_selected_nganh}",
                                        help="Export full quant report as Markdown",
                                    )
                                except Exception:
                                    pass

                    except Exception as _qe:
                        st.caption(f"Quant analysis lỗi: `{_qe}`")

                    # ── Merge Composite score into sector_df for sort + display ──
                    if _sec_scores is not None and not _sec_scores.empty:
                        sector_df = sector_df.copy()
                        sector_df["Composite"] = _sec_scores["composite"].values

                    # Sort
                    if _sort_by == "Composite" and "Composite" in sector_df.columns:
                        sector_df = sector_df.sort_values("Composite", ascending=_sort_asc,
                                                          na_position="last")
                    elif _sort_by in sector_df.columns:
                        sector_df = sector_df.sort_values(_sort_by, ascending=_sort_asc,
                                                          na_position="last")
                    else:
                        sector_df = sector_df.sort_values("Vốn hoá (tỷ)", ascending=False)

                    # Reuse table rendering logic
                    _dd_cols = ["Mã","Composite",
                                "Vốn hoá (tỷ)","Freefloat (tỷ)","GTGD TB (tỷ)",
                                "Vol Avg 5","Vol Avg 10","Vol Avg 20",
                                "AVG 5-10 %","AVG 10-20 %",
                                "Vol 5/Free %","Vol 10/Free %","Vol 20/Free %",
                                "Vol 5/20 %",
                                "Net BS 1T","Net BS 1M","Net BS 3M","Net BS 6M",
                                "NN 1T (tỷ)","NN 1M (tỷ)","NN 3M (tỷ)",
                                "Biên 1T (%)","Biên 1M (%)","Biên 3M (%)",
                                "Giá 1T %","Giá 1M %","Giá 3M %"]
                    _dd_avail = [c for c in _dd_cols if c in sector_df.columns]

                    # Amp scale cho drill-down
                    _dd_amp_vals = []
                    for _ac in _amp_cols:
                        if _ac in sector_df.columns:
                            _dd_amp_vals.extend(sector_df[_ac].dropna().tolist())
                    _dd_amp_min = min(_dd_amp_vals) if _dd_amp_vals else 0
                    _dd_amp_max = max(_dd_amp_vals) if _dd_amp_vals else 1
                    _dd_amp_rng = _dd_amp_max - _dd_amp_min if _dd_amp_max > _dd_amp_min else 1

                    def _dd_amp_color(val):
                        t = max(0, min(1, (float(val) - _dd_amp_min) / _dd_amp_rng))
                        if t < 0.5:
                            r = int(16 + (245 - 16) * (t / 0.5))
                            g = int(185 + (158 - 185) * (t / 0.5))
                            b = int(129 + (11 - 129) * (t / 0.5))
                        else:
                            r = int(245 + (239 - 245) * ((t - 0.5) / 0.5))
                            g = int(158 + (68 - 158) * ((t - 0.5) / 0.5))
                            b = int(11 + (68 - 11) * ((t - 0.5) / 0.5))
                        return f"rgb({r},{g},{b})"

                    # Heatmap scale cho Vol X/Free % trong drill-down (local range)
                    _dd_fvol_vals = []
                    for _fc in _free_vol_cols:
                        if _fc in sector_df.columns:
                            _dd_fvol_vals.extend(v for v in sector_df[_fc].dropna().tolist()
                                                 if isinstance(v, (int, float)) and not np.isnan(v))
                    _dd_fvol_min = min(_dd_fvol_vals) if _dd_fvol_vals else 0
                    _dd_fvol_rng = (max(_dd_fvol_vals) - _dd_fvol_min) if _dd_fvol_vals else 1
                    _dd_fvol_rng = _dd_fvol_rng if _dd_fvol_rng > 0 else 1

                    dd_rows = []
                    for i, (_, row) in enumerate(sector_df.iterrows()):
                        bg = "#0d1117" if i % 2 == 0 else "#111827"
                        cells = []
                        for col in _dd_avail:
                            val = row.get(col)
                            # Format
                            if val is None or (isinstance(val, float) and np.isnan(val)):
                                display = "—"
                                color = "#4b5563"
                            elif col == "Mã":
                                display = str(val)
                                color = "#60a5fa"
                            elif col == "Composite":
                                v = float(val)
                                display = f"{v:+.2f}"
                                # Green for positive, red for negative, intensity by magnitude
                                if v > 1.0:
                                    color = "#10b981"; bg_comp = "#064e3b"
                                elif v > 0.3:
                                    color = "#34d399"; bg_comp = "#065f46"
                                elif v > 0:
                                    color = "#6ee7b7"; bg_comp = "#065f46"
                                elif v > -0.3:
                                    color = "#fca5a5"; bg_comp = "#7f1d1d"
                                elif v > -1.0:
                                    color = "#f87171"; bg_comp = "#7f1d1d"
                                else:
                                    color = "#ef4444"; bg_comp = "#991b1b"
                            elif col in ("Giá 1T %","Giá 1M %","Giá 3M %"):
                                v = float(val)
                                display = f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
                                color = "#10b981" if v > 0 else ("#ef4444" if v < 0 else "#9ca3af")
                            elif col in _nn_cols:
                                v = float(val)
                                display = f"+{v:,.1f}" if v > 0 else f"{v:,.1f}"
                                color = "#10b981" if v > 0 else ("#ef4444" if v < 0 else "#9ca3af")
                            elif col in _net_bs_cols:
                                v = float(val)
                                display = f"+{v:,.1f}M" if v > 0 else f"{v:,.1f}M"
                                color = "#10b981" if v > 0 else ("#ef4444" if v < 0 else "#9ca3af")
                            elif col in ("Vốn hoá (tỷ)","Freefloat (tỷ)","GTGD TB (tỷ)"):
                                display = f"{float(val):,.0f}"
                                color = "#e5e7eb"
                            elif col in ("Vol Avg 5","Vol Avg 10","Vol Avg 20"):
                                display = f"{float(val):,.1f}M"
                                color = "#e5e7eb"
                            elif col == "Vol 5/20 %":
                                v = float(val)
                                display = f"{v:.0f}%"
                                color = "#10b981" if v > 110 else ("#ef4444" if v < 90 else "#e5e7eb")
                            elif col in _avg_vol_cols:
                                v = float(val)
                                display = f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
                                color = "#10b981" if v > 0 else ("#ef4444" if v < 0 else "#9ca3af")
                            elif col in _free_vol_cols:
                                display = f"{float(val):.2f}%"
                                color = "#e5e7eb"
                            else:
                                display = f"{float(val):.1f}%"
                                color = "#e5e7eb"

                            # Render cell
                            if col == "Mã":
                                cells.append(f'<td style="{td_base}color:{color};font-weight:600">{display}</td>')
                            elif col == "Composite" and val is not None and not (isinstance(val, float) and np.isnan(val)):
                                cells.append(f'<td style="{td_base}background:{bg_comp};color:{color};text-align:center;'
                                             f'font-weight:700;border-radius:3px;min-width:60px">{display}</td>')
                            elif col in _amp_cols and val is not None and not (isinstance(val, float) and np.isnan(val)):
                                t = max(0, min(1, (float(val) - _dd_amp_min) / _dd_amp_rng))
                                bar_w = max(4, int(t * 100))
                                bar_c = _dd_amp_color(val)
                                cells.append(
                                    f'<td style="{td_base}padding:4px 6px;min-width:90px">'
                                    f'<div style="display:flex;align-items:center;gap:5px;justify-content:flex-end">'
                                    f'<span style="color:#9ca3af;font-size:11px">{display}</span>'
                                    f'<div style="width:60px;height:14px;background:#1a2234;border-radius:2px;overflow:hidden">'
                                    f'<div style="width:{bar_w}%;height:100%;background:{bar_c};border-radius:2px"></div>'
                                    f'</div></div></td>')
                            elif col in _free_vol_cols and val is not None and not (isinstance(val, float) and np.isnan(val)):
                                bg_c, txt_c = _fvol_colors(val, _dd_fvol_min, _dd_fvol_rng)
                                cells.append(f'<td style="{td_base}background:{bg_c};color:{txt_c};text-align:right;border-radius:3px;font-weight:500">{display}</td>')
                            else:
                                cells.append(f'<td style="{td_base}color:{color};text-align:right">{display}</td>')

                        dd_rows.append(f'<tr style="background:{bg}">' + "".join(cells) + "</tr>")

                    dd_headers = "".join(f'<th style="{th_style}">{c}</th>' for c in _dd_avail)
                    dd_height = min(600, 52 + len(sector_df) * 36)
                    dd_html = f"""<div style="overflow-x:auto;border-radius:8px;border:1px solid #374151;background:#0d1117;max-height:{dd_height}px;overflow-y:auto">
    <table style="width:100%;border-collapse:collapse">
    <thead><tr>{dd_headers}</tr></thead>
    <tbody>{"".join(dd_rows)}</tbody>
    </table></div>"""
                    st.markdown(dd_html, unsafe_allow_html=True)

                    dd_csv = sector_df[_dd_avail].to_csv(index=False, encoding="utf-8-sig")
                    st.download_button(f"⬇️ Export {_selected_nganh}", data=dd_csv,
                                       file_name=f"sector_{_selected_nganh}_{pd.Timestamp.now().strftime('%Y%m%d')}.csv",
                                       mime="text/csv", key="dd_export")
                else:
                    st.info(f"Không có dữ liệu ticker cho ngành {_selected_nganh}")

        # ── Nhận định thị trường ──────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 🧭 Nhận định tổng quan thị trường")

        def _build_commentary(breadth_data, mkt_data, idx_data):
            """Generate market commentary từ data có sẵn."""
            lines = []

            # 1. Đánh giá sức mạnh chung VNINDEX/VN30
            lines.append("**📊 Sức mạnh chung**")
            if idx_data is not None and not idx_data.empty:
                for idx_name in ["VNINDEX", "VN30"]:
                    chg_col = f"{idx_name}_chg"
                    if chg_col in idx_data.columns:
                        recent = idx_data[chg_col].dropna().head(5)
                        avg_chg = recent.mean()
                        up_days = (recent > 0).sum()
                        last_close = idx_data[idx_name].dropna().iloc[0] if idx_name in idx_data.columns else None
                        close_str = f" ({last_close:,.0f})" if last_close else ""
                        if avg_chg > 0.3:
                            trend = "tăng tích cực"
                            icon = "🟢"
                        elif avg_chg > 0:
                            trend = "đi ngang thiên tăng"
                            icon = "🟡"
                        elif avg_chg > -0.3:
                            trend = "đi ngang thiên giảm"
                            icon = "🟠"
                        else:
                            trend = "giảm rõ rệt"
                            icon = "🔴"
                        lines.append(f"- {icon} **{idx_name}**{close_str}: {trend} — 5 phiên gần nhất {up_days}/5 tăng, TB {avg_chg:+.2f}%/phiên")

            # 2. Breadth assessment
            if breadth_data:
                lines.append("")
                lines.append("**🌡️ Sức khỏe thị trường**")
                pct200 = breadth_data["above_ma200_pct"]
                ad = breadth_data["ad_ratio"]
                ov = breadth_data["rsi_oversold"]
                ob = breadth_data["rsi_overbought"]
                nnh = breadth_data["net_new_highs"]

                if pct200 > 50:
                    lines.append(f"- 🟢 {pct200:.0f}% mã trên MA200 — thị trường trong xu hướng tăng rộng")
                elif pct200 > 30:
                    lines.append(f"- 🟡 {pct200:.0f}% mã trên MA200 — thị trường phân hóa, chọn lọc")
                else:
                    lines.append(f"- 🔴 Chỉ {pct200:.0f}% mã trên MA200 — đa số cổ phiếu trong xu hướng giảm")

                if ad > 1.2:
                    lines.append(f"- A/D ratio {ad:.2f} — lực cầu chiếm ưu thế")
                elif ad < 0.8:
                    lines.append(f"- A/D ratio {ad:.2f} — lực bán áp đảo")

                if ov > 50:
                    lines.append(f"- ⚠️ {ov} mã RSI<30 — vùng quá bán rộng, cơ hội nếu có tín hiệu đảo chiều")
                if ob > 30:
                    lines.append(f"- ⚠️ {ob} mã RSI>70 — nhiều mã quá mua, cẩn trọng đuổi giá")

                if nnh > 10:
                    lines.append(f"- {nnh:+d} net new highs — thị trường tạo đỉnh mới tốt")
                elif nnh < -10:
                    lines.append(f"- {nnh:+d} net new highs — nhiều mã tạo đáy mới hơn đỉnh mới")

            # 3. Đánh giá ngành — quant-style scoring
            _has_1m = mkt_data is not None and not mkt_data.empty and "Giá 1M %" in mkt_data.columns
            if _has_1m:
                try:
                    from vnstock_market_analyzer import (
                        compute_scores, market_regime, rank, format_row,
                        session_timing_signal, build_preset_sets,
                        compute_index_returns,
                        load_quarantine_tickers, load_recent_exdiv,
                    )
                    # Load screener presets for ticker-level technical overlay
                    try:
                        from vnstock_dashboard import load_screener_results
                        _preset_sets = build_preset_sets(load_screener_results())
                    except Exception:
                        _preset_sets = None

                    # Load 90-day index data for alpha computation
                    _idx_ret = None
                    try:
                        _idx_long = idx_df  # reuse already-loaded 90d data
                        if _idx_long is not None and not _idx_long.empty:
                            _idx_ret = compute_index_returns(_idx_long, index_col="VNINDEX")
                    except Exception:
                        pass

                    # Quarantine + ex-div filters
                    _quar_set = load_quarantine_tickers()
                    _exdiv_map = load_recent_exdiv(days_back=7)

                    scores = compute_scores(mkt_data, index_returns=_idx_ret,
                                           exdiv_map=_exdiv_map)
                    regime = market_regime(scores, breadth_data)
                    ranked = rank(mkt_data, scores, n_top=5, n_bot=5,
                                  name_col="Ngành", quarantined=_quar_set)

                    lines.append("")
                    lines.append(f"**🧠 Quant regime: {regime['regime']}**  · "
                                 f"conviction `{regime['conviction']:+.2f}` · {regime['detail']}")
                    if _idx_ret:
                        lines.append(f"  · **VNINDEX benchmark**: "
                                     f"1T `{_idx_ret['1T']:+.1f}%` · "
                                     f"1M `{_idx_ret['1M']:+.1f}%` · "
                                     f"3M `{_idx_ret['3M']:+.1f}%` "
                                     f"— alpha dương = outperform")

                    # Session timing signal (institutional vs retail bias)
                    try:
                        from vnstock_session_stats import load_session_stats_history
                        from datetime import date as _td
                        _sess_hist = load_session_stats_history()
                        _today_key = _td.today().isoformat()
                        _today_sess = _sess_hist.get(_today_key)
                        if _today_sess:
                            _st = session_timing_signal(_today_sess, _sess_hist, index_name="VNINDEX")
                            if _st["signal"] != "N/A":
                                lines.append(f"  · **Session timing**: {_st['signal']} — {_st['detail']}")
                    except Exception:
                        pass

                    # Top sectors
                    if ranked["top"]:
                        lines.append("")
                        lines.append("**🎯 Ngành đáng quan tâm (composite cao nhất)**")
                        for row in ranked["top"]:
                            if row.get("composite", 0) <= 0:
                                break  # không show ngành có composite âm
                            for ln in format_row(row, name_col="Ngành"):
                                lines.append(ln if ln.startswith("  ") else f"- {ln}")

                    # Rotation signal (warming-up sectors)
                    if ranked.get("rotation"):
                        lines.append("")
                        lines.append("**🔄 Sector rotation: ngành đang ấm lên (alpha 1M > 3M)**")
                        for row in ranked["rotation"]:
                            for ln in format_row(row, name_col="Ngành"):
                                lines.append(ln if ln.startswith("  ") else f"- {ln}")

                    # Stealth watch
                    if ranked["stealth"]:
                        lines.append("")
                        lines.append("**🕵️ Stealth watch (tín hiệu ẩn, composite chưa mạnh)**")
                        for row in ranked["stealth"]:
                            for ln in format_row(row, name_col="Ngành"):
                                lines.append(ln if ln.startswith("  ") else f"- {ln}")

                    # Distribution warning
                    if ranked["distribution"]:
                        lines.append("")
                        lines.append("**⚠️ Distribution watch (giá tăng nhưng dòng tiền thoát)**")
                        for row in ranked["distribution"]:
                            for ln in format_row(row, name_col="Ngành"):
                                lines.append(ln if ln.startswith("  ") else f"- {ln}")

                    # Avoid list
                    if ranked["avoid"]:
                        lines.append("")
                        lines.append("**⛔ Ngành nên tránh (composite thấp nhất)**")
                        for row in ranked["avoid"]:
                            if row.get("composite", 0) >= 0:
                                break  # không show ngành composite dương
                            for ln in format_row(row, name_col="Ngành"):
                                lines.append(ln if ln.startswith("  ") else f"- {ln}")

                    # Top tickers trong top 3 ngành
                    tick_data = st.session_state.get("_mkt_ticker_data")
                    if (tick_data is not None and not tick_data.empty
                            and "Ngành" in tick_data.columns and ranked["top"]):
                        lines.append("")
                        lines.append("**⭐ Mã dẫn dắt trong ngành top (quant-ranked)**")
                        for sec_row in ranked["top"][:3]:
                            if sec_row.get("composite", 0) <= 0:
                                continue
                            sname = sec_row["Ngành"]
                            sub = tick_data[tick_data["Ngành"] == sname].copy()
                            if sub.empty:
                                continue
                            t_scores = compute_scores(sub, presets=_preset_sets,
                                                     index_returns=_idx_ret, exdiv_map=_exdiv_map)
                            t_ranked = rank(sub, t_scores, n_top=3, n_bot=0,
                                            name_col="Mã", quarantined=_quar_set)
                            picks = []
                            for tr in t_ranked["top"]:
                                if tr.get("composite", 0) <= 0:
                                    continue
                                flag = " 🚨" if tr.get("red_flags") else ""
                                picks.append(
                                    f"**{tr.get('Mã','?')}** (`{tr['composite']:+.2f}`){flag}"
                                )
                            if picks:
                                lines.append(f"- **{sname}**: " + " · ".join(picks))

                    # Mã cần tránh trong ngành tệ nhất (đầu avoid list)
                    if (tick_data is not None and not tick_data.empty
                            and "Ngành" in tick_data.columns and ranked["avoid"]):
                        bad_secs = [r for r in ranked["avoid"] if r.get("composite", 0) < 0][:2]
                        if bad_secs:
                            lines.append("")
                            lines.append("**💀 Mã yếu nhất trong ngành tệ nhất**")
                            for sec_row in bad_secs:
                                sname = sec_row["Ngành"]
                                sub = tick_data[tick_data["Ngành"] == sname].copy()
                                if sub.empty:
                                    continue
                                t_scores = compute_scores(sub, presets=_preset_sets,
                                                         index_returns=_idx_ret, exdiv_map=_exdiv_map)
                                t_ranked = rank(sub, t_scores, n_top=0, n_bot=3,
                                                name_col="Mã", quarantined=_quar_set)
                                flops = []
                                for tr in t_ranked["avoid"]:
                                    if tr.get("composite", 0) >= 0:
                                        continue
                                    flops.append(f"**{tr.get('Mã','?')}** (`{tr['composite']:+.2f}`)")
                                if flops:
                                    lines.append(f"- **{sname}**: " + " · ".join(flops))

                except Exception as _e:
                    lines.append(f"")
                    lines.append(f"⚠️ Không tính được quant score: `{_e}`")

            return "\n".join(lines)

        commentary = _build_commentary(
            breadth if breadth else None,
            mkt_df,
            idx_df if not idx_df.empty else None
        )
        st.markdown(commentary)
        st.caption("⚠️ Nhận định tự động dựa trên dữ liệu kỹ thuật, không phải khuyến nghị đầu tư.")

        # ── Heatmap ngành (Treemap) ────────────────────────────────────────────
        tick_data = st.session_state.get("_mkt_ticker_data")
        _tick_has_1m = tick_data is not None and not tick_data.empty and "Giá 1M %" in tick_data.columns
        if _tick_has_1m:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("#### 🗺️ Heatmap ngành — Vốn hoá & Biến động 1 tháng")
            try:
                import plotly.express as px

                tm_df = tick_data[["Mã","Ngành","Vốn hoá (tỷ)","Giá 1M %"]].copy()
                tm_df = tm_df[tm_df["Vốn hoá (tỷ)"].fillna(0) > 0].dropna(subset=["Giá 1M %"])
                tm_df = tm_df.nlargest(500, "Vốn hoá (tỷ)")

                if not tm_df.empty:
                    fig_tm = px.treemap(
                        tm_df, path=["Ngành", "Mã"],
                        values="Vốn hoá (tỷ)", color="Giá 1M %",
                        color_continuous_scale=["#ef4444","#1f2937","#10b981"],
                        color_continuous_midpoint=0,
                        range_color=[-15, 15],
                        hover_data={"Vốn hoá (tỷ)": ":,.0f", "Giá 1M %": ":+.1f"},
                    )
                    fig_tm.update_layout(
                        height=600,
                        paper_bgcolor="#0a0e1a",
                        font=dict(color="#e5e7eb", size=11),
                        margin=dict(l=5, r=5, t=30, b=5),
                        coloraxis_colorbar=dict(
                            title="1M %", ticksuffix="%",
                            bgcolor="#111827", bordercolor="#1f2937",
                        ),
                    )
                    fig_tm.update_traces(
                        textinfo="label+value",
                        textfont=dict(size=10),
                        hovertemplate="<b>%{label}</b><br>Vốn hoá: %{value:,.0f} tỷ<br>1M: %{color:+.1f}%<extra></extra>",
                    )
                    st.plotly_chart(fig_tm, use_container_width=True)
            except ImportError:
                st.info("Cài plotly để xem heatmap: `pip install plotly`")

        # ── Chart xu hướng ────────────────────────────────────────────────────
        if "Giá 1M %" in mkt_df.columns:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("#### 📈 Biến động giá theo ngành (1 tháng vs 3 tháng)")
            try:
                import plotly.graph_objects as go
                chart_df = mkt_df[mkt_df["Giá 1M %"].notna()].copy()
                chart_df = chart_df.sort_values("Giá 1M %", ascending=True)
                colors1m = ["#10b981" if v > 0 else "#ef4444" for v in chart_df["Giá 1M %"]]

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    y=chart_df["Ngành"], x=chart_df["Giá 1M %"],
                    name="1 Tháng", orientation="h",
                    marker_color=colors1m, opacity=0.85,
                ))
                if "Giá 3M %" in chart_df.columns and chart_df["Giá 3M %"].notna().any():
                    fig.add_trace(go.Scatter(
                        y=chart_df["Ngành"], x=chart_df["Giá 3M %"],
                        name="3 Tháng", mode="markers",
                        marker=dict(color="#fbbf24", size=8, symbol="diamond"),
                    ))
                fig.update_layout(
                    height=max(350, len(chart_df)*22),
                    paper_bgcolor="#0a0e1a", plot_bgcolor="#0d1117",
                    font=dict(color="#9ca3af", size=11),
                    xaxis=dict(gridcolor="#1f2937", zeroline=True,
                               zerolinecolor="#374151", zerolinewidth=2,
                               ticksuffix="%", range=[-30, 30]),
                    yaxis=dict(gridcolor="#1f2937"),
                    margin=dict(l=0, r=80, t=20, b=20),
                    legend=dict(bgcolor="#111827", bordercolor="#1f2937", borderwidth=1),
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.info("Cài plotly để xem chart: `pip install plotly`")

        # ── AI Market Brief ────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🤖 AI Market Brief")

        try:
            from vnstock_brief import (
                load_agent_configs, save_agent_configs, build_agents,
                generate_brief, AGENT_REGISTRY,
            )
            _brief_available = True
        except ImportError:
            _brief_available = False
            st.warning("Không tìm thấy `vnstock_brief.py`. Đảm bảo file tồn tại trong thư mục gốc.")

        if _brief_available:
            # ── Agent settings expander ────────────────────────────────────
            with st.expander("⚙️ Cài đặt AI Agent", expanded=False):
                _agent_configs = load_agent_configs()
                _changed_configs: list[dict] = []

                import os as _os
                for _cfg in _agent_configs:
                    _atype = _cfg.get("type", "")
                    _aname = _cfg.get("name", _atype)
                    # Detect key status
                    _cls = AGENT_REGISTRY.get(_atype)
                    _env_key = getattr(_cls, "_ENV_KEY", "") if _cls else ""
                    _key_ok = bool(_env_key and _os.environ.get(_env_key))
                    _key_badge = (
                        f'<span style="color:#10b981;font-size:12px">🔑 key OK</span>'
                        if _key_ok else
                        f'<span style="color:#ef4444;font-size:12px">🔑 chưa có key</span>'
                    )
                    st.markdown(
                        f"**{_aname}** `{_atype}` &nbsp; {_key_badge}",
                        unsafe_allow_html=True,
                    )
                    _col_en, _col_model, _col_test = st.columns([1, 3, 1])
                    with _col_en:
                        _enabled = st.checkbox(
                            "Bật", value=_cfg.get("enabled", False),
                            key=f"_brief_en_{_atype}",
                            disabled=not _key_ok,
                            help="Cần điền API key vào .env trước" if not _key_ok else "",
                        )
                    with _col_model:
                        _model = st.text_input(
                            "Model", value=_cfg.get("model", ""),
                            key=f"_brief_model_{_atype}",
                            placeholder="e.g. claude-haiku-4-5-20251001",
                        )
                    with _col_test:
                        st.markdown("<div style='margin-top:28px'></div>",
                                    unsafe_allow_html=True)
                        if st.button("🔌 Test", key=f"_brief_ping_{_atype}",
                                     disabled=not _key_ok,
                                     help="Gửi tin nhắn ngắn để kiểm tra key và model"):
                            if _cls:
                                _agent_inst = _cls(
                                    model=st.session_state.get(f"_brief_model_{_atype}",
                                                                _cfg.get("model", "")),
                                    name=_aname,
                                )
                                with st.spinner(f"Đang kiểm tra {_aname}…"):
                                    _ping_ok, _ping_msg = _agent_inst.ping()
                                if _ping_ok:
                                    st.success(_ping_msg)
                                else:
                                    st.error(_ping_msg)
                    _changed_configs.append({**_cfg, "enabled": _enabled, "model": _model})
                    st.markdown("---")

                # Add new agent row
                st.markdown("**Thêm agent mới**")
                _new_col1, _new_col2, _new_col3 = st.columns([1, 2, 2])
                with _new_col1:
                    _new_type = st.selectbox(
                        "Loại", options=list(AGENT_REGISTRY.keys()),
                        key="_brief_new_type",
                    )
                with _new_col2:
                    _new_name = st.text_input(
                        "Tên hiển thị", key="_brief_new_name",
                        placeholder="e.g. GPT-4o",
                    )
                with _new_col3:
                    _new_model = st.text_input(
                        "Model", key="_brief_new_model",
                        placeholder="e.g. gpt-4o",
                    )
                _col_add, _col_save = st.columns([1, 1])
                with _col_add:
                    if st.button("➕ Thêm agent", key="_brief_add_agent"):
                        if _new_name and _new_model:
                            _changed_configs.append({
                                "type": _new_type,
                                "name": _new_name,
                                "model": _new_model,
                                "enabled": True,
                                "max_tokens": 1200,
                            })
                            save_agent_configs(_changed_configs)
                            st.success(f"Đã thêm {_new_name}!")
                            st.rerun()
                        else:
                            st.warning("Vui lòng điền tên và model.")
                with _col_save:
                    if st.button("💾 Lưu cài đặt", key="_brief_save_cfg"):
                        save_agent_configs(_changed_configs)
                        st.success("Đã lưu cài đặt agent!")

                st.caption(
                    "API key đặt trong file `.env` ở thư mục gốc dự án:  \n"
                    "`ANTHROPIC_API_KEY` (Claude) · "
                    "`OPENAI_API_KEY` (OpenAI) · "
                    "`GROQ_API_KEY` (Groq) · "
                    "`MISTRAL_API_KEY` (Mistral) · "
                    "`DEEPSEEK_API_KEY` (DeepSeek) · "
                    "`CEREBRAS_API_KEY` (Cerebras) · "
                    "`OPENROUTER_API_KEY` (OpenRouter)  \n"
                    "Sau khi điền key → restart Streamlit → quay lại đây bật ✅ agent tương ứng."
                )

            # ── Brief controls ─────────────────────────────────────────────
            from datetime import datetime as _dt
            _now_time = _dt.now().time()
            _past_1130 = _now_time.hour > 11 or (_now_time.hour == 11 and _now_time.minute >= 30)
            _past_1500 = _now_time.hour >= 15

            _force_col, _btn_morn_col, _btn_aftn_col = st.columns([2, 1, 1])
            with _force_col:
                _force = st.checkbox(
                    "🔓 Tạo ngay (bỏ qua giờ giao dịch)",
                    key="_brief_force",
                    help="Cho phép tạo brief bất kể thời điểm trong ngày.",
                )
            with _btn_morn_col:
                _morn_disabled = not (_past_1130 or _force)
                _morn_label = "🌅 Morning Brief" if (_past_1130 or _force) else "🌅 Morning (sau 11:30)"
                _gen_morning = st.button(_morn_label, key="_brief_gen_morning", disabled=_morn_disabled)
            with _btn_aftn_col:
                _aftn_disabled = not (_past_1500 or _force)
                _aftn_label = "🌆 Afternoon Brief" if (_past_1500 or _force) else "🌆 Afternoon (sau 15:00)"
                _gen_afternoon = st.button(_aftn_label, key="_brief_gen_afternoon", disabled=_aftn_disabled)

            # ── Generate and cache result ──────────────────────────────────
            if _gen_morning or _gen_afternoon:
                _brief_type = "morning" if _gen_morning else "afternoon"
                _agents = build_agents(load_agent_configs())
                with st.spinner(f"Đang tạo {_brief_type} brief..."):
                    _results = generate_brief(
                        brief_type=_brief_type,
                        agents=_agents if _agents else None,
                        force=_force,
                    )
                st.session_state["_brief_results"] = _results
                st.session_state["_brief_type"] = _brief_type

            # ── Display results ────────────────────────────────────────────
            if "_brief_results" in st.session_state:
                _res = st.session_state["_brief_results"]
                _btype = st.session_state.get("_brief_type", "morning")
                _btype_label = "Morning" if _btype == "morning" else "Afternoon"

                if "_timing" in _res:
                    st.info(_res["_timing"][1])
                elif "_no_agent" in _res:
                    st.warning(_res["_no_agent"][1])
                else:
                    st.markdown(f"**{_btype_label} Brief** — {_dt.now().strftime('%H:%M %d/%m/%Y')}")
                    _agent_names = [k for k in _res if not k.startswith("_")]

                    # ── Consensus banner (multi-agent only) ────────────────
                    if len(_agent_names) >= 2:
                        try:
                            from vnstock_brief import derive_consensus
                            _cons = derive_consensus(_res)
                            if _cons.get("n_agents", 0) >= 2 and _cons.get("consensus_line"):
                                _stance_top = max(_cons["stance"].items(),
                                                  key=lambda kv: kv[1])[0]
                                _icon = {"bullish": "🟢", "bearish": "🔴",
                                         "neutral": "🟡", "unknown": "⚪"}.get(_stance_top, "🟡")
                                st.markdown(
                                    f"### {_icon} Consensus — "
                                    f"{_cons['consensus_line']}"
                                )
                                # Per-agent stance row
                                _stance_emoji = {"bullish": "🟢", "bearish": "🔴",
                                                 "neutral": "🟡", "unknown": "⚪"}
                                _badges = [
                                    f"{_stance_emoji.get(info['stance'], '⚪')} "
                                    f"`{nm}` {info['stance']}"
                                    for nm, info in _cons["per_agent"].items()
                                ]
                                st.caption(" · ".join(_badges))
                                # Sector + ticker breakdown
                                _c_sec, _c_tk = st.columns(2)
                                with _c_sec:
                                    if _cons["top_sectors"]:
                                        _sec_lines = " · ".join(
                                            f"**{s}** ({c}/{_cons['n_agents']})"
                                            for s, c in _cons["top_sectors"][:5]
                                        )
                                        st.caption(f"📊 Ngành: {_sec_lines}")
                                with _c_tk:
                                    if _cons["top_tickers"]:
                                        _tk_lines = " · ".join(
                                            f"**{t}** ({c})"
                                            for t, c in _cons["top_tickers"][:6]
                                        )
                                        st.caption(f"🎯 Tickers: {_tk_lines}")
                                st.divider()
                        except Exception as _ce:
                            st.caption(f"⚠ consensus disabled: {type(_ce).__name__}: {_ce}")

                    def _rating_block(agent_name: str, brief_type_: str):
                        try:
                            import vnstock_memory as _vm
                            _vm.init_db()
                            _today = _dt.now().date().isoformat()
                            with _vm._conn() as _c:
                                _row = _c.execute(
                                    "SELECT id, user_rating FROM briefs "
                                    "WHERE brief_date=? AND brief_type=? AND agent_name=? "
                                    "ORDER BY created_at DESC LIMIT 1",
                                    (_today, brief_type_, agent_name),
                                ).fetchone()
                            if not _row:
                                return
                            _bid = _row["id"]
                            _existing = _row["user_rating"]
                            _key_pref = f"_rate_{_bid}"
                            _cols = st.columns([2, 5, 2])
                            with _cols[0]:
                                _rate = st.select_slider(
                                    "⭐ Đánh giá",
                                    options=[1, 2, 3, 4, 5],
                                    value=_existing or 3,
                                    key=f"{_key_pref}_v",
                                )
                            with _cols[1]:
                                _fb = st.text_input(
                                    "Feedback (optional)",
                                    placeholder="Mô tả vấn đề / điểm cần cải thiện...",
                                    key=f"{_key_pref}_fb",
                                )
                            with _cols[2]:
                                if st.button("💾 Lưu", key=f"{_key_pref}_save"):
                                    _vm.update_rating(_bid, int(_rate), _fb or "")
                                    st.success("Đã lưu", icon="✅")
                        except Exception as _e:
                            st.caption(f"⚠ rating disabled: {type(_e).__name__}")

                    # Hallucination warnings collected by validate_brief_factuality
                    _warn_map = _res.get("_warnings") or {}

                    def _render_warnings(agent_name: str) -> None:
                        ws = _warn_map.get(agent_name) or []
                        for w in ws:
                            st.error(w, icon="🚨")

                    if len(_agent_names) == 1:
                        _txt, _err = _res[_agent_names[0]]
                        if _err:
                            st.error(f"**{_agent_names[0]}:** {_err}")
                        else:
                            with st.expander(f"📄 {_agent_names[0]}", expanded=True):
                                _render_warnings(_agent_names[0])
                                st.markdown(_txt)
                                _rating_block(_agent_names[0], _btype)
                    elif _agent_names:
                        _tabs = st.tabs([f"📄 {n}" for n in _agent_names])
                        for _tab, _aname in zip(_tabs, _agent_names):
                            with _tab:
                                _txt, _err = _res[_aname]
                                if _err:
                                    st.error(_err)
                                else:
                                    _render_warnings(_aname)
                                    st.markdown(_txt)
                                    _rating_block(_aname, _btype)

                st.caption("Brief được tạo bởi AI dựa trên dữ liệu quant — không phải khuyến nghị đầu tư.")

            # ── F4: Brief accuracy leaderboard (compact widget) ──────────────
            try:
                import vnstock_memory as _vml
                from vnstock_brief import agent_accuracy_summary as _aasl
                _vml.init_db()
                _recent = _vml.recent_briefs(brief_type=None, limit=200)
                if _recent:
                    _ldr = _aasl(_recent, horizon_days=1, neutral_threshold_pct=0.5)
                    # Only show agents with at least 1 evaluated brief
                    _ranked = sorted(
                        [(n, s) for n, s in _ldr.items()
                         if (s.get("n_evaluated") or 0) > 0],
                        key=lambda kv: -(kv[1].get("accuracy") or 0),
                    )
                    if _ranked:
                        st.markdown("**🏆 Bảng xếp hạng độ chính xác agent (T+1, 200 briefs gần nhất)**")
                        _lc = st.columns(min(len(_ranked), 5))
                        for _i, (_nm, _slot) in enumerate(_ranked[:5]):
                            _acc = _slot.get("accuracy") or 0
                            _ne  = _slot.get("n_evaluated") or 0
                            _emoji = "🥇" if _i == 0 else "🥈" if _i == 1 else "🥉" if _i == 2 else "🎖"
                            _color = (
                                "#22c55e" if _acc >= 0.6
                                else "#fbbf24" if _acc >= 0.5
                                else "#ef4444"
                            )
                            with _lc[_i]:
                                st.markdown(
                                    f"<div style='text-align:center;padding:8px;"
                                    f"border:1px solid {_color};border-radius:6px;"
                                    f"background:rgba(30,41,59,0.4)'>"
                                    f"<div style='font-size:18px'>{_emoji} <b>{_nm}</b></div>"
                                    f"<div style='font-size:24px;color:{_color};font-weight:700'>"
                                    f"{_acc*100:.0f}%</div>"
                                    f"<div style='font-size:11px;color:#9ca3af'>"
                                    f"{_slot.get('n_match',0)} / {_ne} matched</div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                        st.caption(
                            "💡 Agent #1 nên dùng làm primary trong Consensus. "
                            "Cần ≥ 10 briefs evaluated/agent để có ý nghĩa thống kê."
                        )
            except Exception:
                pass

            # ── Brief history viewer ────────────────────────────────────────
            with st.expander("📜 Lịch sử brief (rated & past)", expanded=False):
                try:
                    import vnstock_memory as _vmh
                    import json as _jsonh
                    _vmh.init_db()
                    _hc1, _hc2, _hc3 = st.columns([2, 2, 4])
                    with _hc1:
                        _hfilter = st.selectbox(
                            "Loại",
                            ["tất cả", "morning", "afternoon"],
                            key="_brief_hist_type",
                        )
                    with _hc2:
                        _hlimit = st.number_input(
                            "Số lượng",
                            min_value=5, max_value=100, value=20, step=5,
                            key="_brief_hist_limit",
                        )
                    with _hc3:
                        _hmin_rate = st.select_slider(
                            "Rating tối thiểu (0 = tất cả)",
                            options=[0, 1, 2, 3, 4, 5],
                            value=0,
                            key="_brief_hist_min_rate",
                        )
                    _btype_filter = None if _hfilter == "tất cả" else _hfilter
                    _hist = _vmh.recent_briefs(_btype_filter, limit=int(_hlimit))
                    if _hmin_rate > 0:
                        _hist = [r for r in _hist
                                 if (r.get("user_rating") or 0) >= _hmin_rate]
                    if not _hist:
                        st.info("Chưa có brief nào trong DB phù hợp filter.")
                    else:
                        # Per-agent accuracy summary (F1.c)
                        try:
                            from vnstock_brief import (
                                agent_accuracy_summary as _aas,
                                _load_vnindex_closes as _lvc,
                                evaluate_brief_accuracy as _eba,
                            )
                            _closes = _lvc()
                            _hcols = st.columns([1, 1, 3])
                            with _hcols[0]:
                                _acc_horizon = st.selectbox(
                                    "Đánh giá tại",
                                    [1, 2, 3, 5],
                                    format_func=lambda d: f"T+{d}",
                                    key="_brief_acc_horizon",
                                )
                            with _hcols[1]:
                                _acc_thresh = st.selectbox(
                                    "Ngưỡng flat",
                                    [0.3, 0.5, 1.0],
                                    index=1,
                                    format_func=lambda p: f"±{p}%",
                                    key="_brief_acc_thresh",
                                )
                            with _hcols[2]:
                                st.caption(
                                    "**Cách tính**: stance của brief vs % thay đổi "
                                    "VNINDEX T+horizon. |return| dưới ngưỡng = flat. "
                                    "Brief 'unknown' bị bỏ qua khỏi mẫu."
                                )
                            _summary = _aas(
                                _hist,
                                horizon_days=int(_acc_horizon),
                                neutral_threshold_pct=float(_acc_thresh),
                            )
                            if _summary:
                                st.markdown("**📊 Độ chính xác per-agent**")
                                _rows = []
                                for _name, _slot in sorted(
                                    _summary.items(),
                                    key=lambda kv: -(kv[1].get("accuracy") or 0)
                                ):
                                    _acc = _slot.get("accuracy")
                                    _acc_str = (
                                        f"{_acc*100:.0f}%" if _acc is not None else "—"
                                    )
                                    _sd = _slot.get("stance_dist", {})
                                    _stance_str = (
                                        f"🟢{_sd.get('bullish',0)} "
                                        f"🟡{_sd.get('neutral',0)} "
                                        f"🔴{_sd.get('bearish',0)} "
                                        f"⚪{_sd.get('unknown',0)}"
                                    )
                                    _rows.append({
                                        "Agent": _name,
                                        "Accuracy": _acc_str,
                                        "Match / Eval": f"{_slot.get('n_match',0)} / {_slot.get('n_evaluated',0)}",
                                        "Total briefs": _slot.get("n_total", 0),
                                        "Stance dist": _stance_str,
                                    })
                                st.dataframe(_rows, hide_index=True,
                                             use_container_width=True)
                            st.divider()
                        except Exception as _ae:
                            st.caption(f"⚠ accuracy summary disabled: {type(_ae).__name__}: {_ae}")
                            _closes = None
                            _eba = None  # type: ignore[assignment]

                        # Group by date
                        from collections import defaultdict as _dd
                        _by_date: dict = _dd(list)
                        for _b in _hist:
                            _by_date[_b.get("brief_date", "?")].append(_b)
                        for _date in sorted(_by_date.keys(), reverse=True):
                            _bs = _by_date[_date]
                            _rates = [b.get("user_rating") for b in _bs
                                      if b.get("user_rating")]
                            _avg = f"{sum(_rates)/len(_rates):.1f}⭐" if _rates else "—"
                            _types = sorted({b.get("brief_type", "?") for b in _bs})
                            st.markdown(
                                f"**{_date}** · {len(_bs)} briefs · "
                                f"{','.join(_types)} · avg {_avg}"
                            )
                            for _b in _bs:
                                _r = _b.get("user_rating")
                                _stars = "⭐" * _r if _r else "—"
                                _scr = _b.get("auto_score")
                                _scrs = f" · auto {_scr:.1f}" if isinstance(_scr, (int, float)) else ""
                                _err = _b.get("error") or ""
                                # Per-brief match indicator
                                _match_badge = ""
                                _eval_info = None
                                if _eba is not None and not _err:
                                    try:
                                        _eval_info = _eba(
                                            _b, closes=_closes,
                                            horizon_days=int(_acc_horizon),
                                            neutral_threshold_pct=float(_acc_thresh),
                                        )
                                        _m = _eval_info.get("match")
                                        if _m is True:
                                            _match_badge = " · ✅ match"
                                        elif _m is False:
                                            _match_badge = " · ❌ miss"
                                        else:
                                            _match_badge = " · ⏳ pending"
                                    except Exception:
                                        _eval_info = None
                                _lbl = (f"{_b.get('brief_type','?')} · "
                                        f"{_b.get('agent_name','?')} · "
                                        f"{_stars}{_scrs}{_match_badge}"
                                        f"{' · ⚠ error' if _err else ''}")
                                with st.expander(_lbl, expanded=False):
                                    _ctx_raw = _b.get("context_json") or "{}"
                                    try:
                                        _cctx = _jsonh.loads(_ctx_raw)
                                        _vt = (_cctx.get("vnindex_tech") or {})
                                        _vclose = _vt.get("close")
                                        if _vclose:
                                            st.caption(
                                                f"📌 VNINDEX lúc brief: {_vclose:,.2f}"
                                            )
                                    except Exception:
                                        pass
                                    if _eval_info and _eval_info.get("eval_date"):
                                        _ret = _eval_info.get("return_pct")
                                        _ret_str = (
                                            f"{_ret:+.2f}%" if _ret is not None else "—"
                                        )
                                        st.caption(
                                            f"🎯 Stance **{_eval_info['stance']}** vs "
                                            f"actual **{_eval_info['actual']}** "
                                            f"({_eval_info['baseline_close']:,.2f} → "
                                            f"{_eval_info['eval_close']:,.2f} = {_ret_str} "
                                            f"trên {int(_acc_horizon)} phiên)"
                                        )
                                    elif _eval_info and _eval_info.get("reason"):
                                        st.caption(
                                            f"🎯 _Chưa đánh giá được: {_eval_info['reason']}_"
                                        )
                                    if _err:
                                        st.error(_err)
                                    if _b.get("output"):
                                        st.markdown(_b["output"])
                                    if _b.get("user_feedback"):
                                        st.caption(
                                            f"💬 Feedback: {_b['user_feedback']}"
                                        )
                except Exception as _e:
                    st.caption(f"⚠ history disabled: {type(_e).__name__}: {_e}")

            # ── Strategy & recommendations panel ───────────────────────────
            with st.expander("🧪 Chiến lược & khuyến nghị (auto-trained)", expanded=False):
                try:
                    import vnstock_memory as _vm
                    _vm.init_db()
                    _active  = _vm.get_active_family()
                    _bests   = _vm.best_strategies(limit=5)
                    _opens   = _vm.open_recommendations()
                    _perf    = _vm.recommendation_performance()

                    _c1, _c2, _c3 = st.columns(3)
                    _c1.metric("Active strategy", "✅" if _active else "—")
                    _c2.metric("Open recommendations", len(_opens))
                    _c3.metric(
                        "Win rate (closed)",
                        f"{_perf.get('win_rate', 0)*100:.0f}%" if _perf.get("n", 0) else "—",
                        delta=f"n={_perf.get('n', 0)}",
                    )

                    # Always show the current active strategy
                    if _active:
                        import json as _json
                        _fam = _active.get("family_id", "?")
                        _tuned_by = _active.get("agent_name", "?")
                        _stable = "✅ stable" if _active.get("is_core_stable") else "🔄 revising"
                        _tuned_at = (_active.get("last_tuned_at") or _active.get("created_at", ""))[:10]

                        st.markdown("**Chiến lược đang hoạt động**")
                        _sa, _sb = st.columns([3, 2])
                        with _sa:
                            st.write(
                                f"**{_active['name']}**  \n"
                                f"Family `{_fam}` · {_stable} · tuned {_tuned_at}"
                            )
                        with _sb:
                            # Show latest backtest from family history
                            _hist = _vm.family_history(_fam, limit=1)
                            if _hist and _hist[0].get("n_trades") is not None:
                                _h = _hist[0]
                                _nt = _h.get("n_trades", 0)
                                _exp = _h.get("expectancy") or 0.0
                                _wr = (_h.get("win_rate") or 0.0) * 100
                                st.metric("Expectancy", f"{_exp:.2f}", delta=f"{_nt} trades")
                                if _nt == 0:
                                    st.warning(
                                        "⚠️ **0 trades** — strategy conditions chưa trigger được. "
                                        "Nhấn **Fresh start** bên dưới để generate chiến lược mới.",
                                        icon="⚠️",
                                    )
                                elif _nt < 10:
                                    st.warning(f"⚠️ Chỉ {_nt} trades — backtest window còn nhỏ, cần chạy Full training.", icon="⚠️")
                            else:
                                st.caption("Chưa có backtest metrics.")

                        with st.expander("Xem params & code", expanded=False):
                            try:
                                _params = _json.loads(_active.get("params_json") or "{}")
                                st.code(_json.dumps(_params, indent=2, ensure_ascii=False), language="json")
                            except Exception:
                                pass
                            _code = _active.get("code") or ""
                            if _code:
                                st.code(_code[:1500] + ("…" if len(_code) > 1500 else ""), language="python")

                        # ── F6: Equity Curve & Trade Analysis ─────────────
                        with st.expander("📈 Equity Curve & Phân tích backtest", expanded=False):
                            try:
                                import plotly.graph_objects as _go
                                import numpy as _np

                                _bt_row = _vm.latest_backtest(_active["id"])
                                _bt_metrics = (
                                    _json.loads(_bt_row["metrics_json"])
                                    if _bt_row and _bt_row.get("metrics_json")
                                    else {}
                                )
                                _trades_raw = _bt_metrics.get("trades", [])

                                if not _trades_raw:
                                    st.info("Chưa có dữ liệu trades. Chạy training để tạo backtest.")
                                else:
                                    _pnls  = [t["pnl"] for t in _trades_raw]
                                    _cum   = _np.cumsum(_pnls).tolist()
                                    _peak  = _np.maximum.accumulate(_cum).tolist()
                                    _dd    = [c - p for c, p in zip(_cum, _peak)]
                                    _n     = len(_pnls)
                                    _idxs  = list(range(1, _n + 1))

                                    _bar_colors = [
                                        "#22c55e" if p > 0 else "#ef4444" if p < 0 else "#94a3b8"
                                        for p in _pnls
                                    ]

                                    # Chart 1: PnL bar + equity line
                                    _fig1 = _go.Figure()
                                    _fig1.add_trace(_go.Bar(
                                        x=_idxs, y=_pnls,
                                        marker_color=_bar_colors,
                                        name="PnL / lệnh (%)",
                                        opacity=0.55,
                                    ))
                                    _fig1.add_trace(_go.Scatter(
                                        x=_idxs, y=_cum,
                                        mode="lines",
                                        line=dict(color="#60a5fa", width=2),
                                        name="Equity tích lũy (%)",
                                        yaxis="y2",
                                    ))
                                    _fig1.update_layout(
                                        title=f"Equity Curve — {_n} lệnh",
                                        yaxis=dict(title="PnL / lệnh (%)", zeroline=True, zerolinecolor="#475569"),
                                        yaxis2=dict(
                                            title="Cumulative PnL (%)",
                                            overlaying="y", side="right",
                                            zeroline=True, zerolinecolor="#475569",
                                        ),
                                        height=300,
                                        legend=dict(orientation="h", y=1.12),
                                        margin=dict(l=0, r=0, t=45, b=0),
                                        plot_bgcolor="#0e1117",
                                        paper_bgcolor="#0e1117",
                                        font=dict(color="#f1f5f9"),
                                    )
                                    st.plotly_chart(_fig1, use_container_width=True)

                                    # Chart 2: Drawdown
                                    _fig2 = _go.Figure()
                                    _fig2.add_trace(_go.Scatter(
                                        x=_idxs, y=_dd,
                                        fill="tozeroy",
                                        fillcolor="rgba(239,68,68,0.20)",
                                        line=dict(color="#ef4444", width=1.5),
                                        name="Drawdown (%)",
                                    ))
                                    _fig2.update_layout(
                                        title="Drawdown",
                                        yaxis=dict(title="Drawdown (%)", zeroline=True, zerolinecolor="#475569"),
                                        height=180,
                                        margin=dict(l=0, r=0, t=40, b=0),
                                        plot_bgcolor="#0e1117",
                                        paper_bgcolor="#0e1117",
                                        font=dict(color="#f1f5f9"),
                                    )
                                    st.plotly_chart(_fig2, use_container_width=True)

                                    # Outcome breakdown metrics
                                    _reasons = [t.get("reason", "?") for t in _trades_raw]
                                    _r_tp = _reasons.count("tp")
                                    _r_sl = _reasons.count("sl")
                                    _r_ex = _reasons.count("expire")
                                    _max_dd = min(_dd)
                                    _final  = _cum[-1]
                                    _mc1, _mc2, _mc3, _mc4, _mc5 = st.columns(5)
                                    _mc1.metric("🎯 Hit TP",   _r_tp, f"{_r_tp/_n*100:.0f}%")
                                    _mc2.metric("🛑 Hit SL",   _r_sl,
                                                f"-{_r_sl/_n*100:.0f}%", delta_color="inverse")
                                    _mc3.metric("⏰ Hết hạn",  _r_ex, f"{_r_ex/_n*100:.0f}%")
                                    _mc4.metric("Max Drawdown", f"{_max_dd:.1f}%")
                                    _mc5.metric("Net Return",   f"{_final:+.1f}%",
                                                delta_color="normal" if _final >= 0 else "inverse")
                            except Exception as _e6:
                                st.caption(f"Equity curve không khả dụng: {_e6}")
                    else:
                        st.info("Chưa có chiến lược nào. Nhấn **Lite training** để bắt đầu.", icon="ℹ️")

                    # Top strategies with enough trades
                    if _bests:
                        st.markdown("**Top strategies (n_trades ≥ 10)**")
                        for _s in _bests:
                            st.write(
                                f"- #{_s['id']} {_s['name']}"
                                f" — exp={_s.get('expectancy', 0):.2f}"
                                f" | win={_s.get('win_rate', 0):.0%}"
                                f" | trades={_s.get('n_trades', 0)}"
                            )

                    if _opens:
                        st.markdown("**Open recommendations**")
                        import pandas as _pd
                        from datetime import datetime as _dt_cls
                        _df_opens = _pd.DataFrame(_opens)
                        # Add % vs entry next to each price target — easier
                        # than mental math to gauge risk/reward at a glance.
                        _entry = _df_opens["entry_price"].astype(float)
                        _tp_pct = (_df_opens["take_profit"].astype(float) / _entry - 1) * 100
                        _sl_pct = (_df_opens["cut_loss"].astype(float)    / _entry - 1) * 100
                        _df_opens["TP (%)"] = _tp_pct.round(1).map(lambda v: f"{v:+.1f}%")
                        _df_opens["SL (%)"] = _sl_pct.round(1).map(lambda v: f"{v:+.1f}%")
                        _df_opens["R:R"] = (_tp_pct / _sl_pct.abs().replace(0, _pd.NA)).round(2)

                        # Show age + horizon status so user sees what's expired
                        def _age_status(row):
                            try:
                                created = _dt_cls.fromisoformat(str(row["created_at"]))
                            except Exception:
                                return "—"
                            age = (_dt_cls.now() - created).days
                            horizon = int(row.get("horizon_days") or 5)
                            if age >= horizon:
                                return f"🕒 {age}d (đến hạn — bấm Cập nhật)"
                            return f"⏳ {age}/{horizon}d"

                        _df_opens["Trạng thái"] = _df_opens.apply(_age_status, axis=1)
                        st.dataframe(
                            _df_opens[
                                ["ticker", "action", "entry_price",
                                 "take_profit", "TP (%)",
                                 "cut_loss",    "SL (%)", "R:R",
                                 "Trạng thái", "created_at"]
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )

                        # Reconcile button — close expired recs by walking
                        # forward from price history. Same logic as the daily
                        # train script's reconcile_recommendations().
                        _rc1, _rc2 = st.columns([1, 3])
                        with _rc1:
                            if st.button("📊 Cập nhật kết quả",
                                         key="_reconcile_btn",
                                         help="Đóng các khuyến nghị đã quá horizon "
                                              "(walk-forward giá để check TP/SL/expire). "
                                              "Tự động chạy khi `vnstock_train.py --once`."):
                                with st.spinner("⏳ Đang reconcile..."):
                                    try:
                                        from vnstock_train import reconcile_recommendations as _rec_fn
                                        _rc_summary = _rec_fn(verbose=False)
                                        st.session_state["_reconcile_result"] = _rc_summary
                                    except Exception as _e:
                                        st.session_state["_reconcile_result"] = {
                                            "error": f"{type(_e).__name__}: {_e}"
                                        }
                                st.rerun()
                        with _rc2:
                            _rc_res = st.session_state.get("_reconcile_result")
                            if _rc_res:
                                if _rc_res.get("error"):
                                    st.error(f"❌ {_rc_res['error']}")
                                else:
                                    st.success(
                                        f"✅ Đã đóng **{_rc_res.get('closed', 0)}** rec, "
                                        f"còn **{_rc_res.get('still_open', 0)}** đang mở."
                                    )

                    # ── Closed recommendations + outcome breakdown ─────────
                    try:
                        _closed = _vm.recent_closed_recommendations(limit=20)
                        _dist   = _vm.outcome_distribution()
                    except Exception:
                        _closed, _dist = [], {}

                    # Filter out superseded entries from the visible table —
                    # they're administrative closures, not real outcomes.
                    _closed_real = [
                        c for c in _closed
                        if (c.get("hit_target") or "") != "superseded"
                    ]

                    if _dist or _closed_real:
                        st.markdown("**📈 Kết quả khuyến nghị đã đóng**")
                        _n_tp = _dist.get("tp", 0)
                        _n_sl = _dist.get("sl", 0)
                        _n_ex = _dist.get("expire", 0)
                        _n_sup = _dist.get("superseded", 0)
                        _n_real = _n_tp + _n_sl + _n_ex
                        _o1, _o2, _o3, _o4 = st.columns(4)
                        _o1.metric("🎯 Hit TP", _n_tp,
                                   delta=f"{_n_tp/_n_real*100:.0f}%" if _n_real else None)
                        _o2.metric("🛑 Hit SL", _n_sl,
                                   delta=f"-{_n_sl/_n_real*100:.0f}%" if _n_real else None,
                                   delta_color="inverse")
                        _o3.metric("⏰ Hết hạn", _n_ex)
                        _o4.metric("🔄 Bị thay thế", _n_sup,
                                   help="Đóng khi scan mới ra khuyến nghị thay thế cho cùng mã.")

                        if _closed_real:
                            import pandas as _pd
                            _df_cl = _pd.DataFrame(_closed_real)
                            _icon_map = {"tp": "🎯 TP", "sl": "🛑 SL", "expire": "⏰ Hết hạn"}
                            _df_cl["Kết quả"] = _df_cl["hit_target"].map(_icon_map).fillna(_df_cl["hit_target"])
                            _df_cl["P&L %"] = _df_cl["pnl_pct"].astype(float).round(2).map(
                                lambda v: f"{v:+.2f}%" if _pd.notna(v) else "—"
                            )
                            _df_cl["entry_price"] = _df_cl["entry_price"].astype(float).round(0)
                            _df_cl["exit_price"] = _df_cl["exit_price"].astype(float).round(0)
                            with st.expander(
                                f"Xem {len(_closed_real)} khuyến nghị gần đây nhất",
                                expanded=False,
                            ):
                                st.dataframe(
                                    _df_cl[[
                                        "ticker", "action", "entry_price",
                                        "exit_price", "P&L %", "Kết quả",
                                        "horizon_days", "created_at", "closed_at",
                                    ]],
                                    use_container_width=True,
                                    hide_index=True,
                                )
                        st.caption(
                            "💡 Hệ thống TỰ động đóng rec khi đến hạn (horizon ngày) — "
                            "walk-forward giá để check TP/SL/expire. "
                            "Reconcile chạy tự động mỗi khi gọi `python vnstock_train.py --once`, "
                            "hoặc bấm **📊 Cập nhật kết quả** ở trên để chạy ngay."
                        )

                    # ── Training result ────────────────────────────────────
                    if st.session_state.get("_train_result"):
                        _tr = st.session_state["_train_result"]
                        if _tr.get("error"):
                            st.error(f"❌ {_tr['error']}")
                        else:
                            _sl_r = _tr.get("strategy_loop", {})
                            _msg = (
                                f"✅ **Training xong** — "
                                f"agents={_sl_r.get('agents_run',0)} | "
                                f"mode={_sl_r.get('mode','?')} | "
                                f"n_trades={_tr.get('n_trades','?')} | "
                                f"expectancy={_tr.get('expectancy','?')}"
                            )
                            if _sl_r.get("errors"):
                                st.warning(f"⚠️ Có lỗi: {_sl_r['errors']}")
                            else:
                                st.success(_msg)

                    st.divider()
                    _train_col1, _train_col2 = st.columns(2)

                    def _run_training(lite: bool, mode: str = "auto") -> None:
                        """Chỉ train chiến lược — không emit recommendations."""
                        try:
                            from vnstock_train import (
                                strategy_loop as _sl_fn,
                                brief_loop as _bl_fn,
                            )
                            _bl_fn(verbose=False)
                            _sl_out = _sl_fn(verbose=False, lite=lite, mode=mode)
                            _nt, _exp = "?", "?"
                            _nf = _vm.get_active_family()
                            if _nf:
                                _nh = _vm.family_history(_nf.get("family_id", ""), limit=1)
                                if _nh:
                                    _nt  = _nh[0].get("n_trades", "?")
                                    _exp = round(_nh[0].get("expectancy") or 0, 2)
                            st.session_state["_train_result"] = {
                                "strategy_loop": _sl_out,
                                "n_trades": _nt,
                                "expectancy": _exp,
                            }
                        except Exception as _e:
                            import traceback as _tb
                            st.session_state["_train_result"] = {
                                "error": f"{type(_e).__name__}: {_e}\n{_tb.format_exc()[-800:]}"
                            }
                        st.rerun()

                    with _train_col1:
                        if st.button("⚡ Lite training (~60-90s)", key="_train_lite",
                                     help="17 mã (10 VN30 + 7 VNMID đa ngành), backtest nhanh."):
                            st.session_state["_train_result"] = None
                            with st.spinner("⏳ Đang chạy… (60-90s nếu cần revise code)"):
                                _run_training(lite=True, mode="auto")
                    with _train_col2:
                        if st.button("🚀 Full training (~15-25 min)", key="_train_full",
                                     help="~50 mã (VN30 đủ + 20 VNMID), full walk-forward. CHẬM."):
                            st.session_state["_train_result"] = None
                            with st.spinner("⏳ Đang chạy full training… 15-25 phút"):
                                _run_training(lite=False, mode="auto")

                    # Fresh start button — shown when strategy hasn't reached validation threshold
                    _cur_nt = 0
                    if _active:
                        _fh = _vm.family_history(_active.get("family_id", ""), limit=1)
                        _cur_nt = (_fh[0].get("n_trades") or 0) if _fh else 0
                    if _cur_nt < 10:
                        if st.button("🔄 Fresh start (generate chiến lược mới hoàn toàn)",
                                     key="_train_fresh",
                                     help="Generate code chiến lược hoàn toàn mới. "
                                          "Dùng khi strategy < 10 trades hoặc logic sai."):
                            st.session_state["_train_result"] = None
                            with st.spinner("⏳ Đang generate chiến lược mới… (15-30s API call)"):
                                _run_training(lite=True, mode="fresh")

                    st.caption(
                        "ℹ️ Lite: 10 VN30 + 7 VNMID = 17 mã, backtest nhanh (~60-90s). "
                        "Full: VN30 đủ + 20 VNMID = ~50 mã (~15-25 phút, nên dùng Task Scheduler). "
                        "Sau khi train, bấm **Quét tín hiệu** để tìm khuyến nghị."
                    )

                    # ── Scan recommendations (độc lập với training) ────────
                    st.divider()
                    st.markdown("**🔍 Quét tín hiệu toàn thị trường**")
                    st.caption(
                        "Áp chiến lược hiện có lên toàn bộ kho dữ liệu. "
                        "Chỉ quét mã có khối lượng trung bình ≥ 100.000 cổ/ngày."
                    )

                    if st.session_state.get("_scan_result"):
                        _sr = st.session_state["_scan_result"]
                        if _sr.get("error"):
                            st.error(f"❌ {_sr['error']}")
                        elif _sr.get("reason") == "no_validated_strategy":
                            st.warning("⚠️ Chưa có chiến lược validated. Chạy training thêm để đạt ≥ 10 trades.")
                        else:
                            _n_recs = _sr.get("n_recs", 0)
                            _diag   = _sr.get("diag", {})
                            if _n_recs:
                                st.success(f"✅ Đã quét **{_sr.get('n_scanned',0)}** mã → **{_n_recs}** khuyến nghị mới")
                            else:
                                st.info(f"ℹ️ Quét **{_sr.get('n_scanned',0)}** mã → 0 khuyến nghị (điều kiện mua chưa kích hoạt hôm nay)")
                            if _diag:
                                _n_err = _diag.get('n_errors', 0)
                                _err_color = "🔴" if _n_err else "🟢"
                                st.caption(
                                    f"📊 Không có data: **{_diag.get('n_no_data',0)}** · "
                                    f"Dưới 100K vol: **{_diag.get('n_low_vol',0)}** · "
                                    f"Chạy được: **{_diag.get('n_executed',0)}** · "
                                    f"Hold/Sell: **{_diag.get('n_hold',0)}** · "
                                    f"Buy signal: **{_diag.get('n_buy',0)}** · "
                                    f"{_err_color} Errors: **{_n_err}**"
                                )
                                _samples = _diag.get('errors_sample') or []
                                if _samples:
                                    with st.expander(
                                        f"⚠️ {_n_err} mã throw exception — xem mẫu lỗi",
                                        expanded=(_diag.get('n_executed', 0) == 0),
                                    ):
                                        st.caption(
                                            "Strategy code fail silent. Sửa code trong DB "
                                            "(`brief_memory.db` → `strategies.code`) hoặc "
                                            "Fresh start để generate lại."
                                        )
                                        for s in _samples:
                                            st.code(
                                                f"[{s.get('example_ticker','?')}] "
                                                f"{s.get('error','')}",
                                                language="text",
                                            )

                    if st.button("🔍 Quét tín hiệu toàn thị trường", key="_scan_recs",
                                 help="Quét toàn bộ kho, lọc vol ≥ 100K cổ/ngày, tối đa 5 recs."):
                        st.session_state["_scan_result"] = None
                        with st.spinner("⏳ Đang quét… (vài giây đến 1 phút tuỳ kho)"):
                            try:
                                from vnstock_train import _scan_universe as _su_fn
                                from vnstock_strategy import emit_recommendations as _emit_fn
                                _su = _su_fn()
                                _all = _emit_fn(_su, max_recs=5, min_avg_volume=100_000)
                                # Last element is always the _stats sentinel
                                _diag_item = _all[-1] if _all and _all[-1].get("_stats") else {}
                                _real_recs = [r for r in _all if not r.get("_stats")]
                                st.session_state["_scan_result"] = {
                                    "n_scanned": len(_su),
                                    "n_recs": len(_real_recs),
                                    "diag": _diag_item,
                                    "reason": _diag_item.get("reason", ""),
                                }
                            except Exception as _e:
                                import traceback as _tb
                                st.session_state["_scan_result"] = {
                                    "error": f"{type(_e).__name__}: {_e}\n{_tb.format_exc()[-600:]}"
                                }
                        st.rerun()
                except Exception as _e:
                    st.caption(f"Strategy panel disabled: {type(_e).__name__}: {_e}")
