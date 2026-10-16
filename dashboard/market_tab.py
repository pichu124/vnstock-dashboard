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
lazy-imported inside the render function.

Tách đợt 12/08 (mục ④ audit 06/08) — ``render_market_tab`` từ 2.544
dòng xuống ~1.040:

* ``dashboard/market_brief_panel.py`` — khối 🤖 AI Market Brief (1.172
  dòng: cài đặt agent, consensus, lịch sử, panel chiến lược, training,
  scan). Đo bằng AST trước khi cắt: khối chỉ cần ĐÚNG MỘT tên từ scope
  ngoài (``st``).
* ``dashboard/market_commentary.py`` — 🧭 Nhận định tổng quan (220 dòng
  SINH CHỮ cho user). ``st.session_state`` + ``idx_df`` trước bắt qua
  closure, nay là tham số.
* ``dashboard/market_table_format.py`` — thang màu + định dạng ô bảng
  ngành. ``_amp_color`` từng bị chép nguyên thành ``_dd_amp_color`` cho
  drill-down; nay một hàm nhận (min, range) làm tham số.
* ``dashboard/sparkline.py`` — SVG sparkline alpha 30 phiên.

Còn inline: ``_live_market_fragment`` — fragment Streamlit
(``@st.fragment``), theo thiết kế phải nằm trong hàm render.
"""

from __future__ import annotations

# Tổng bề rộng các ô heatmap VN30 tính theo bề ngang khung (%): 300 ≈ 3 hàng
# cho 30 mã. Tăng = ô to hơn/nhiều hàng hơn, giảm = dẹt lại. Xem khối
# "Chiều rộng ô ≈ VỐN HOÁ" trong `_live_market_fragment` để biết vì sao là
# flex-basis % chứ không phải flex-grow.
_HEATMAP_WIDTH_SPAN = 300.0


def _symmetric_xrange(*series, floor: float = 30.0) -> list:
    """Trục x đối xứng quanh 0 cho chart % ngành: ±max(floor, max|x|×1.1).

    Mọi |x|×1.1 ≤ floor → giữ khung cũ [-30, 30]; ngành chạy ±42% thì nới
    ra thay vì bị cắt khỏi khung. NaN bỏ qua (`v == v`)."""
    peak = max((abs(float(v)) for s in series for v in s if v == v), default=0.0)
    r = max(floor, peak * 1.1)
    return [-r, r]


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
    from dashboard.sparkline import sparkline_svg as _sparkline_svg

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

    @st.cache_data(ttl=300, show_spinner=False)
    def _overview_freshness() -> dict:
        """Cache vì `effective_trading_date` đọc VNINDEX + bars live của phiên."""
        from vnstock_brief import market_data_freshness
        return market_data_freshness()

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
        # mtime < 24h chưa đủ: overview chốt TRƯỚC 15:05 của phiên là giữa phiên.
        _fr = _overview_freshness()
        if _fr["stale"]:
            _why = (f"chốt giữa phiên {_fr['overview_time']} — chưa trọn"
                    if _fr["reason"] == "intraday"
                    else f"là phiên trước ({_fr['overview_date']}) — chưa có")
            st.caption(f"⚠️ Market overview {_why} phiên {_fr['data_date']} "
                       f"(độ rộng, dòng tiền ngành, regime).")
    except Exception as e:
        st.caption(f"⚠️ Badge độ tươi lỗi: {type(e).__name__}: {e}")

    # ── Live Market Heatmap (VN30 real-time) ──────────────────────────────
    if st.session_state.get("live_mode") and WSS_AVAILABLE:
        # run_every=2 khớp POLL_INTERVAL của động cơ (20/08). Để 5s thì dù
        # dữ liệu tươi 2s, ô vẫn đứng im tới 5s — user báo "phản hồi chậm"
        # chính là độ trễ CỘNG DỒN này, không phải độ trễ của feed.
        @st.fragment(run_every=2)
        def _live_market_fragment():
            # Rổ VN30 HIỆN HÀNH (HOSE đổi rổ 2 lần/năm) — không phải hằng số
            # chép cứng. Đi qua `vnstock_dashboard` chứ không import thẳng
            # `vnstock_wss`: tab này lấy MỌI hằng số live từ đó, và test dựng
            # module giả ở đúng chỗ đó.
            try:
                import vnstock_dashboard as _vd
                _basket = list(_vd.get_vn30_symbols())
            except Exception:
                _basket = VN30_SYMBOLS
            if not _basket:
                _basket = VN30_SYMBOLS
            _vn30_quotes = []
            for _sym in _basket:
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

            # Chiều rộng ô ≈ VỐN HOÁ TƯƠNG ĐỐI (user chốt 18/08). Cap lấy từ
            # bảng ticker screener (`_mkt_ticker_data` — có thể CHƯA có ở lượt
            # render đầu vì fragment đứng TRƯỚC phần thân tab; lượt refresh 5s
            # sau tự có) → thiếu cap thì mọi ô rộng bằng nhau như trước.
            #
            # Ba quyết định đo bằng trình duyệt thật trước khi chốt (18/08):
            # 1. NÉN sqrt — cap VIC/POW chênh 24× mà bề rộng chỉ chênh ~4.5×:
            #    ô nhỏ vẫn đọc được chữ, tương quan lớn/nhỏ vẫn thấy ngay.
            # 2. flex-basis THEO % (`flex:0 1 x%`) chứ KHÔNG phải flex-grow:
            #    grow chỉ chia phần thừa nên min-width nuốt hết chênh lệch
            #    (đo được: 28/30 ô dính đúng 80px, tỷ lệ chết).
            # 3. grow = 0: hàng cuối để lề phải so le, KHÔNG kéo giãn ô cuối
            #    (đo bản grow=1: TCB phình 575px — bề rộng nói dối vốn hoá).
            # `_HEATMAP_WIDTH_SPAN` ≈ tổng bề rộng tính theo màn hình → ~3 hàng.
            import math as _math
            _cap_by_tk: dict = {}
            try:
                _td = st.session_state.get("_mkt_ticker_data")
                if _td is not None and "Mã" in _td.columns \
                        and "Vốn hoá (tỷ)" in _td.columns:
                    for _ma, _cap in zip(_td["Mã"], _td["Vốn hoá (tỷ)"]):
                        if _cap and float(_cap) > 0:
                            _cap_by_tk[str(_ma)] = float(_cap)
            except Exception:
                _cap_by_tk = {}
            _w_of = {_q["ticker"]: _math.sqrt(_cap_by_tk[_q["ticker"]])
                     for _q in _vn30_quotes if _q.get("ticker") in _cap_by_tk}
            # Mã thiếu cap đi trọng số TRUNG VỊ: không nổi bật cũng không teo.
            _w_known = sorted(_w_of.values())
            _w_mid = _w_known[len(_w_known) // 2] if _w_known else 1.0
            _w_total = sum(_w_of.get(_q.get("ticker"), _w_mid)
                           for _q in _vn30_quotes) or 1.0

            # VN30 Heatmap
            _lbl_extra = " · rộng ô ≈ vốn hoá" if _w_known else ""
            st.markdown(
                "<div style='color:#6b7280;font-size:11px;margin-bottom:6px;"
                "text-transform:uppercase;letter-spacing:0.08em'>"
                f"🔴 VN30 Heatmap — Real-time{_lbl_extra}</div>",
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
                _pct = (_w_of.get(_tk, _w_mid) / _w_total) * _HEATMAP_WIDTH_SPAN
                _flex = (f"flex:0 1 {_pct:.2f}%" if _w_known else "flex:1 1 0")
                _cap_note = (f" title='{_tk}: vốn hoá ~{_cap_by_tk[_tk]:,.0f} tỷ'"
                             if _tk in _cap_by_tk else "")
                _cells += (
                    f"<div{_cap_note} style='background:{_bg};border-radius:4px;"
                    f"padding:6px 4px;overflow:hidden;"
                    f"text-align:center;min-width:64px;{_flex}'>"
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
    elif WSS_AVAILABLE:
        # Đừng vắng mặt ÂM THẦM (bài học 17/08: khối im lặng thì không ai
        # phân biệt được "chưa bật live" với "cờ chết") — cờ tắt thì nói rõ
        # đường bật. Dòng này kiêm luôn "chứng chỉ code mới" khi nghi máy
        # đang chạy bản cũ.
        st.caption(
            "🔌 Live Mode tắt — bật **Real-time WSS** ở sidebar bên trái "
            "(mục 🔴 Live Mode) để xem chỉ số + heatmap VN30 real-time tại đây."
        )

    # ── Chỉ số thị trường ────────────────────────────────────────────────────
    # Load 90 ngày một lần, reuse cho sparklines + quant analysis + commentary
    with st.spinner("Đang tải dữ liệu chỉ số..."):
        idx_df = load_index_overview(days=90)

    if not idx_df.empty:
        _idx_rows = idx_df.head(20)
        st.markdown(f"#### 📈 Diễn biến chỉ số thị trường ({len(_idx_rows)} phiên)")
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
        for i, (_, row) in enumerate(_idx_rows.iterrows()):
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

    # ── Brief 3 khung (P1b-6, #24): badge trung hạn + ngắn hạn — try RIÊNG ──
    try:
        if _badges := _horizon_badges():
            st.markdown(" &nbsp;·&nbsp; ".join(f"**{b}**" for b in _badges))
    except Exception as e:
        st.caption(f"⚠️ Brief 3 khung lỗi: {type(e).__name__}: {e}")

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
    except Exception as e:   # regime là khối phụ: không kéo sập tab, nhưng phải NÓI ra
        st.caption(f"⚠️ Market regime lỗi: {type(e).__name__}: {e}")

    # ── Market Overview theo ngành (dữ liệu đã load ở trên) ─────────────────
    if mkt_df.empty:
        st.warning("Không có dữ liệu.")
    else:
        # ── Metric cards ───────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        total_sectors = len(mkt_df)
        total_mktcap  = mkt_df["Vốn hoá (tỷ)"].sum() if "Vốn hoá (tỷ)" in mkt_df.columns else 0
        total_vol20   = mkt_df["Vol Avg 20"].sum()
        # Bảng sắp theo vốn hoá ⇒ iloc[0] KHÔNG phải ngành KLGD cao nhất.
        _vol20 = mkt_df["Vol Avg 20"].dropna()
        top_row = mkt_df.loc[_vol20.idxmax()] if not _vol20.empty else None
        top_sector = str(top_row["Ngành"]) if top_row is not None else "—"
        top_vol20 = f'{float(top_row["Vol Avg 20"]):.0f}M cp' if top_row is not None else "—"

        with c1:
            st.markdown(f'<div class="metric-card"><div class="label">Số ngành</div><div class="value">{total_sectors}</div><div class="sub">đã phân loại</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><div class="label">Tổng vốn hoá</div><div class="value">{total_mktcap/1000:,.0f} nghìn tỷ</div><div class="sub">VND</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card"><div class="label">KLGD TB 20 ngày</div><div class="value">{total_vol20:,.0f}M</div><div class="sub">triệu cổ phiếu</div></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="metric-card"><div class="label">Ngành KLGD cao nhất</div><div class="value">{top_sector[:14]}</div><div class="sub">Vol 20: {top_vol20}</div></div>', unsafe_allow_html=True)

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

        # ── Thang màu + định dạng ô → dashboard/market_table_format.py ────────
        # Thang màu nhận (min, range) làm THAM SỐ: bảng tổng và bảng drill-down
        # dùng chung một hàm với hai thang khác nhau (trước đây là 2 bản chép).
        from dashboard.market_table_format import (
            AMP_COLS as _amp_cols,
            AVG_VOL_COLS as _avg_vol_cols,
            FREE_VOL_COLS as _free_vol_cols,
            NET_BS_COLS as _net_bs_cols,
            NN_COLS as _nn_cols,
            amp_color as _amp_color_at,
            fmt,
            fvol_colors as _fvol_colors_at,
            scale_range,
        )
        from dashboard.market_table_format import color_val as _color_val_at

        _amp_vals = [v for c in _amp_cols if c in mkt_df.columns
                     for v in mkt_df[c].dropna().tolist()]
        _amp_min, _amp_max, _amp_range = scale_range(_amp_vals)

        # Heatmap scale cho Vol X/Free % — dùng chung cho sector + drill-down
        _fvol_vals = [v for c in _free_vol_cols if c in mkt_df.columns
                      for v in mkt_df[c].dropna().tolist()]
        _fvol_min, _fvol_max, _fvol_rng = scale_range(_fvol_vals)

        def _amp_color(val):
            return _amp_color_at(val, _amp_min, _amp_range)

        def _fvol_colors(val, fmin=None, frng=None):
            return _fvol_colors_at(val,
                                   _fvol_min if fmin is None else fmin,
                                   _fvol_rng if frng is None else frng)

        def color_val(val, col):
            return _color_val_at(val, col, _amp_min, _amp_range)

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
            except Exception as e:
                _sparklines = {}
                st.caption(f"⚠️ Sparkline α 30d lỗi: {type(e).__name__}: {e}")

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
                # Nhóm tuỳ biến ("Họ VIN", "Họ M") phải lọc theo DANH SÁCH MÃ:
                # bảng mã giữ `Ngành` = ngành gốc nên so chuỗi luôn ra rỗng.
                from vnstock_sectors import rows_for_sector
                sector_df = rows_for_sector(tick_data, _selected_nganh).copy()
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

                    # Amp scale RIÊNG cho drill-down (thang trong 1 ngành, không
                    # phải thang toàn thị trường) — cùng hàm màu, khác thang.
                    _dd_amp_vals = [v for c in _amp_cols if c in sector_df.columns
                                    for v in sector_df[c].dropna().tolist()]
                    _dd_amp_min, _dd_amp_max, _dd_amp_rng = scale_range(_dd_amp_vals)

                    def _dd_amp_color(val):
                        return _amp_color_at(val, _dd_amp_min, _dd_amp_rng)

                    # Heatmap scale cho Vol X/Free % trong drill-down (thang cục bộ).
                    # Bản cũ ở đây tính `max - min` KHÔNG có chốt chặn range=0 mà
                    # bản bảng tổng lại có — mọi giá trị bằng nhau là chia 0.
                    # `scale_range` gộp hai bản nên lệch kiểu này hết đường xảy ra.
                    _dd_fvol_vals = [v for c in _free_vol_cols if c in sector_df.columns
                                     for v in sector_df[c].dropna().tolist()]
                    _dd_fvol_min, _dd_fvol_max, _dd_fvol_rng = scale_range(_dd_fvol_vals)
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

        # Nhận định thị trường → dashboard/market_commentary.py.
        # `idx_df` và bảng mã trong session_state trước bắt qua closure,
        # nay truyền THAM SỐ nên hàm sinh chữ test được.
        from dashboard.market_commentary import build_commentary

        commentary = build_commentary(
            breadth if breadth else None,
            mkt_df,
            idx_df if not idx_df.empty else None,
            idx_long=idx_df,
            tick_data=st.session_state.get("_mkt_ticker_data"),
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
                               ticksuffix="%",
                               range=_symmetric_xrange(chart_df["Giá 1M %"],
                                                       chart_df.get("Giá 3M %", ()))),
                    yaxis=dict(gridcolor="#1f2937"),
                    margin=dict(l=0, r=80, t=20, b=20),
                    legend=dict(bgcolor="#111827", bordercolor="#1f2937", borderwidth=1),
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.info("Cài plotly để xem chart: `pip install plotly`")

        # ── AI Market Brief → dashboard/market_brief_panel.py ─────────────
        from dashboard.market_brief_panel import render_brief_panel
        render_brief_panel()


def _horizon_badges() -> list[str]:
    """Badge trung hạn + ngắn hạn (+ 🚨) từ bản published 3 khung — rỗng khi công
    tắc VNSTOCK_HORIZONS tắt. Chỉ đọc state đã lưu (pipeline tối ghi)."""
    from vnstock_horizons import MEDIUM_LABEL, SHORT_LABEL, horizons_enabled
    if not horizons_enabled():
        return []
    from vnstock_brief_canon import _hz_ddmm, _hz_signed, _hz_weeks
    try:
        import vnstock_horizons_state as hs
        v = hs.brief_view(hs.latest_published())
    except Exception:
        return ["🔭 3 khung: chưa đọc được state"]
    if v.get("stale") or not isinstance(v.get("snap"), dict):
        return [f"🔭 3 khung: chưa cập nhật (as_of {_hz_ddmm(v.get('as_of'))})"]
    s = v["snap"]
    out = [f"🔭 Trung hạn: {MEDIUM_LABEL.get(s.get('medium'), '?')} "
           f"(từ {_hz_ddmm(s.get('medium_since'))}, {_hz_weeks(v)})",
           f"Ngắn hạn: {SHORT_LABEL.get(s.get('short'), '?')} (phiên {v.get('short_sessions')})"
           f" · điểm {_hz_signed(s.get('score'))}/{s.get('n')}"]
    if tier := (s.get("alert") or {}).get("tier"):
        out.append(f"🚨 Rủi ro ngắn hạn: mức {tier}")
    return out
