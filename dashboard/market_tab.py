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

    import json
    import numpy as np
    import pandas as pd
    from datetime import datetime, timedelta
    from pathlib import Path

    from vnstock_dashboard import (
        INDEX_SYMBOLS, VN30_SYMBOLS, WSS_AVAILABLE,
        load_index_overview, load_live_quote, load_market_overview,
    )

    col_title_m, col_ref_m = st.columns([6,1])
    with col_title_m:
        st.markdown("### 🌏 Tổng quan thị trường theo ngành")
    with col_ref_m:
        if st.button("🔄", key="market_refresh", help="Refresh"):
            st.cache_data.clear()
            st.rerun()

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
    with st.spinner("Đang tải dữ liệu chỉ số..."):
        idx_df = load_index_overview(days=30)

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
        _sort_cols = ["Vốn hoá (tỷ)","GTGD TB (tỷ)","Vol Avg 20","Vol 5/20 %",
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
            # ── Bảng ngành (sorted) ───────────────────────────────────────────
            if _sort_by in mkt_df.columns:
                mkt_df = mkt_df.sort_values(_sort_by, ascending=_sort_asc, na_position="last").reset_index(drop=True)
            rows_html = []
            for i, (_, row) in enumerate(mkt_df.iterrows()):
                bg = "#0d1117" if i%2==0 else "#111827"
                cells = []
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

            headers = "".join(f'<th style="{th_style}">{c}</th>' for c in avail_cols)
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
                               mime="text/csv")

            if not has_foreign:
                st.caption("⚠️ Dữ liệu dòng ngoại (NN) chưa có — cần vnstock API `Trading.foreign_trade()`. "
                           "Vốn hoá là ước tính từ giá × cổ phiếu lưu hành. Freefloat từ dữ liệu cổ đông lớn (KBS).")

        # ── Drill-down: chi tiết công ty theo ngành ───────────────────────────
        if _selected_nganh != "Tổng quan theo ngành":
            tick_data = st.session_state.get("_mkt_ticker_data")
            if tick_data is not None and not tick_data.empty:
                sector_df = tick_data[tick_data["Ngành"] == _selected_nganh].copy()
                if not sector_df.empty:
                    if _sort_by in sector_df.columns:
                        sector_df = sector_df.sort_values(_sort_by, ascending=_sort_asc, na_position="last")
                    else:
                        sector_df = sector_df.sort_values("Vốn hoá (tỷ)", ascending=False)
                    st.markdown(f"#### 🏢 Chi tiết ngành: {_selected_nganh} ({len(sector_df)} mã)")

                    # Reuse table rendering logic
                    _dd_cols = ["Mã","Vốn hoá (tỷ)","Freefloat (tỷ)","GTGD TB (tỷ)",
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

            # 3. Đánh giá ngành
            _has_1m = mkt_data is not None and not mkt_data.empty and "Giá 1M %" in mkt_data.columns
            if _has_1m:
                lines.append("")
                lines.append("**🏭 Nhóm ngành nổi bật**")

                # Ngành nên tập trung: Giá 1M > 0 AND Vol 5/20 > 100
                _has_vol = "Vol 5/20 %" in mkt_data.columns
                focus = mkt_data[
                    (mkt_data["Giá 1M %"].fillna(0) > 0) &
                    (mkt_data["Vol 5/20 %"].fillna(0) > 95 if _has_vol else True)
                ].sort_values("Giá 1M %", ascending=False)

                if not focus.empty:
                    lines.append("- 🟢 **Nên tập trung:** " + ", ".join(
                        f'{r["Ngành"]} ({r["Giá 1M %"]:+.1f}%)'
                        for _, r in focus.head(5).iterrows()
                    ))
                else:
                    lines.append("- 🟡 Không có ngành nào vừa tăng giá 1M vừa có thanh khoản tốt")

                # Ngành nên tránh: Giá 1M < -3% OR (Giá 3M < -5% AND Vol giảm)
                _has_3m = "Giá 3M %" in mkt_data.columns
                _avoid_cond = (mkt_data["Giá 1M %"].fillna(0) < -3)
                if _has_3m and _has_vol:
                    _avoid_cond = _avoid_cond | ((mkt_data["Giá 3M %"].fillna(0) < -5) & (mkt_data["Vol 5/20 %"].fillna(100) < 85))
                avoid = mkt_data[_avoid_cond].sort_values("Giá 1M %", ascending=True)

                if not avoid.empty:
                    lines.append("- 🔴 **Nên tránh:** " + ", ".join(
                        f'{r["Ngành"]} ({r["Giá 1M %"]:+.1f}%)'
                        for _, r in avoid.head(5).iterrows()
                    ))

                # 4. Top cổ phiếu trong ngành focus
                tick_data = st.session_state.get("_mkt_ticker_data")
                _tick_ok = (tick_data is not None and "Giá 1M %" in tick_data.columns
                            and "Vol Avg 20" in tick_data.columns)
                if _tick_ok and not focus.empty:
                    lines.append("")
                    lines.append("**⭐ Cổ phiếu đáng chú ý trong ngành trọng tâm**")
                    for _, sector_row in focus.head(3).iterrows():
                        sector_name = sector_row["Ngành"]
                        tickers = tick_data[tick_data["Ngành"] == sector_name].copy()
                        if tickers.empty:
                            continue
                        top = tickers[
                            (tickers["Giá 1M %"].fillna(0) > 0) &
                            (tickers["Vol Avg 20"].fillna(0) > 0.5)
                        ].sort_values("Giá 1M %", ascending=False).head(3)
                        if not top.empty:
                            picks = ", ".join(
                                f'**{r["Mã"]}** (1M:{r["Giá 1M %"]:+.1f}%, VH:{r["Vốn hoá (tỷ)"]:,.0f}tỷ)'
                                for _, r in top.iterrows()
                            )
                            lines.append(f"- {sector_name}: {picks}")

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
