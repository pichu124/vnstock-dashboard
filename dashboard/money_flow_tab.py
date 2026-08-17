"""
Dòng Tiền tab — 💰 sector-level money-flow dashboard.

Shows foreign net buying, buy/sell ratio, and large-order activity per
sector with a composite score. Feeds from three cached data sources:
* ``_fetch_foreign_net_flow`` — foreign net flow per ticker (TopStock API)
* ``_fetch_order_stats_batch`` — large-order stats (order_stats endpoint)
* ``_batch_load_live_quotes``  — realtime quote snapshot (WSS)

Extraction notes
----------------
All heavy helpers stay in ``vnstock_dashboard.py`` and are lazy-imported
inside ``render_money_flow_tab`` so the module remains importable for
unit tests without the Streamlit runtime. The cache-clear helper, the
``_pick_gtgd`` closure, and the ``_live_money_flow_fragment`` fragment
live inline inside this module.
"""

from __future__ import annotations


# ── Custom sector groups ("Họ VIN", "Họ M", …) ────────────────────────────
# Membership/labels live in the dependency-free vnstock_sectors module (shared
# with the brief/screener pipeline so each group means the same set everywhere).
# The order/icon overrides stay local to render_money_flow_tab.
from vnstock_sectors import (  # noqa: E402
    CUSTOM_SECTOR_ORDER as _CUSTOM_SECTOR_ORDER,
    custom_sector_for as _custom_sector_for,
)


def render_money_flow_tab() -> None:
    """Render the Dòng Tiền tab. Lazy imports Streamlit + dashboard helpers."""
    try:
        import streamlit as st
    except ImportError:
        print("[money_flow_tab] streamlit not available")
        return

    import json
    import numpy as np
    import sys
    import pandas as pd
    from pathlib import Path

    # Streamlit registers the main script as 'main' (not 'vnstock_dashboard')
    # in sys.modules. Register the alias so the lazy import below resolves
    # to the already-loaded module instead of triggering a fresh import.
    if 'vnstock_dashboard' not in sys.modules:
        _m = sys.modules.get('__main__') or sys.modules.get('main')
        if _m and hasattr(_m, 'PRICES_DIR'):
            sys.modules['vnstock_dashboard'] = _m

    # All dashboard-level helpers + constants — lazy import to avoid
    # circular deps at load time. Safe at call time because
    # vnstock_dashboard has finished initialising before dispatch fires.
    from vnstock_dashboard import (
        PRICES_DIR, SECTOR_ICONS, SECTOR_ORDER, WSS_AVAILABLE,
        _NN_CACHE_PATH, _NN_DIAG, _ORDER_CACHE_PATH,
        _aggregate_nn_buy_sell_by_window, _aggregate_nn_by_window,
        _batch_load_live_quotes,
        _compute_gtgd_by_window, _compute_money_flow_score,
        _fetch_foreign_net_flow, _fetch_order_stats_batch,
        _get_sector, _is_stock, _load_industry_map,
        _score_bar_html, _score_label,
    )

    # ── Custom-group order + icon overrides (membership rules live in
    # vnstock_sectors). Custom groups are pinned to the FRONT, in registry order
    # (Họ VIN, Họ M, …). Scoped to this tab only: the shared SECTOR_ORDER /
    # _get_sector stay untouched so the training universe and portfolio sector
    # logic keep their original mapping.
    _MF_SECTOR_ORDER = [*_CUSTOM_SECTOR_ORDER, *SECTOR_ORDER]
    _MF_SECTOR_ICONS = {**SECTOR_ICONS, "Họ VIN": "🅥", "Họ M": "Ⓜ️"}

    def _mf_sector(symbol: str, industry: str) -> str:
        """Money-flow sector: custom-group ticker → its label, else shared mapping."""
        return _custom_sector_for(symbol) or _get_sector(industry)

    st.markdown("### 💰 Dòng Tiền Ngành")

    # Data staleness badges
    try:
        from pathlib import Path as _Path
        from vnstock_freshness import render_freshness_row
        render_freshness_row([
            ("💸 NN flow",         _Path("data_warehouse/_meta/nn_flow_cache.json"),    2 * 3600),
            ("📊 Order stats",     _Path("data_warehouse/_meta/order_stats_cache.json"), 2 * 3600),
        ])
    except Exception:
        pass

    # ── Sidebar controls ─────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### 💰 Dòng Tiền")
        _mf_window = st.radio(
            "Khung thời gian NN ròng",
            ["1D", "5D", "20D"],
            index=1,
            horizontal=True,
            key="mf_window",
            help=(
                "Tổng NN ròng (khối ngoại mua - bán) theo khung thời gian:\n\n"
                "- **1D**: ngày giao dịch gần nhất (hôm nay nếu đang giao dịch, "
                "hoặc ngày T-1 nếu ngoài giờ / cuối tuần).\n"
                "- **5D**: 5 ngày — xu hướng tuần, lọc nhiễu ngày.\n"
                "- **20D**: 20 ngày — xu hướng tháng, tay to tích/xả dần.\n\n"
                "**Lưu ý**: chỉ **NN ròng** thay đổi theo khung. Các cột "
                "**GTGD**, **Vol**, **Buy/Sell** luôn là **snapshot hôm nay** "
                "(từ live quotes), không đổi theo 1D/5D/20D."
            ),
        )
        _mf_days = {"1D": 0, "5D": 7, "20D": 30}[_mf_window]
        # Consumer của động cơ WSS (user chốt 17/08): động cơ tắt thì toggle
        # bị KHOÁ + kéo về OFF kèm chỉ đường, khỏi bật chay vô dụng.
        _wss_engine_on = bool(st.session_state.get("live_mode")) and WSS_AVAILABLE
        if not _wss_engine_on:
            st.session_state["mf_live"] = False
        _mf_live_on = st.toggle(
            "Live Scan (real-time)",
            key="mf_live",
            disabled=not _wss_engine_on,
            help=(
                "**Bật**: cập nhật Buy/Sell ratio mỗi 15 giây từ live quote "
                "data (chỉ hoạt động khi 🔴 Live Mode đang bật ở sidebar trái).\n\n"
                "**Tắt**: chỉ xem dữ liệu offline (NN ròng + Buy/Sell từ "
                "lần poll gần nhất).\n\n"
                "Live Scan **không có NN ròng** real-time (dữ liệu NN chỉ "
                "có cuối ngày) — chỉ dựa trên tỷ lệ Buy/Sell volume."
            ),
        )
        if not _wss_engine_on:
            st.caption("🔌 Cần bật **🔴 Live Mode** ở sidebar trái trước.")
        st.caption(
            "**NN ròng**: khối ngoại mua - bán ròng (tỷ VND)\n\n"
            "**Buy/Sell**: tỷ lệ mua/bán chủ động "
            "(top 50 mã từ `order_stats`, còn lại từ bid/ask depth)\n\n"
            "**Lệnh lớn**: avg order size hôm nay vs 20 ngày "
            "(top 50 mã từ `order_stats`)\n\n"
            "**Score** = 40% × NN + 35% × Buy/Sell + 25% × Lệnh lớn"
        )

    # ── Load industry map ────────────────────────────────────────────────
    _ind_map = _load_industry_map()
    if not _ind_map:
        st.warning("⚠️ Chưa có `industry_classification.parquet`. "
                   "Chạy `python vnstock_classifier.py` trước.")
        st.stop()

    # ── Collect tickers per sector ───────────────────────────────────────
    _sector_tickers = {}
    for tk, ind in _ind_map.items():
        if not _is_stock(tk):
            continue
        sector = _mf_sector(tk, ind)
        _sector_tickers.setdefault(sector, []).append(tk)

    # ── Fetch foreign net flow (TopStock API) ────────────────────────────
    _all_tickers = [tk for tks in _sector_tickers.values() for tk in tks]
    _warehouse_tickers_all = [
        tk for tk in _all_tickers
        if (PRICES_DIR / f"ticker={tk}").exists()
    ]

    # Nút xoá cache (debug khi NN = 0)
    with st.sidebar:
        if st.button("🗑 Xoá cache", key="mf_clear_cache", help=(
            "Xoá cache NN ròng + Lệnh lớn (disk + RAM) → force re-fetch từ API. "
            "Dùng khi NN ròng hiện 0 hoặc data cũ."
        )):
            _fetch_foreign_net_flow.clear()
            _fetch_order_stats_batch.clear()
            _NN_DIAG.clear()
            for _cp in (_NN_CACHE_PATH, _ORDER_CACHE_PATH):
                if _cp.exists():
                    _cp.unlink()
            st.rerun()

    with st.spinner("Đang tải dữ liệu NN ròng (TopStock API)..."):
        _nn_raw = _fetch_foreign_net_flow(trading_days=20, limit=100)

    # Diagnostic
    _nn_record_count = len(_nn_raw) if not _nn_raw.empty else 0
    if _nn_record_count == 0:
        st.warning(
            "⚠️ Không tải được dữ liệu NN ròng từ TopStock API. "
            "Thử bấm **🗑 Xoá cache NN** trong sidebar, hoặc kiểm tra "
            "kết nối internet + vnstock_data sponsor."
        )

    # Aggregate NN ròng + Mua/Bán theo window đã chọn (1D/5D/20D)
    _nn_by_ticker = _aggregate_nn_by_window(_nn_raw, _mf_days)  # {symbol: tỷ VND}
    _nn_bs_by_ticker = _aggregate_nn_buy_sell_by_window(_nn_raw, _mf_days)

    # Diagnostic: warn if foreign_buy() data is missing (NN Mua = 0 for all)
    _total_buy = sum(v.get("buy", 0) for v in _nn_bs_by_ticker.values())
    _total_sell = sum(v.get("sell", 0) for v in _nn_bs_by_ticker.values())
    if _total_buy == 0 and _total_sell > 0:
        with st.expander("⚠️ NN Mua = 0 — debug info (foreign_buy)"):
            _buy_state = _NN_DIAG.get("buy_state", "unknown (fetch loop may not have run — cache hit)")
            _sell_state = _NN_DIAG.get("sell_state", "unknown")
            st.caption(f"**foreign_buy state:** {_buy_state}")
            st.caption(f"**foreign_sell state:** {_sell_state}")
            if "buy_cols" in _NN_DIAG:
                st.caption(f"**Buy rows:** {_NN_DIAG['buy_rows']}")
                st.caption(f"**Buy columns:** {_NN_DIAG['buy_cols']}")
                st.caption(f"**Buy sample row:** {_NN_DIAG['buy_sample']}")
            if "sell_cols" in _NN_DIAG:
                st.caption(f"**Sell columns:** {_NN_DIAG['sell_cols']}")
                st.caption(f"**Sell sample row:** {_NN_DIAG['sell_sample']}")

    # GTGD aggregated across the same window (1D=latest session, 5D=5 trading
    # days, 20D=20 trading days). Always use warehouse for consistency.
    # For 1D, _compute_gtgd_by_window(1) gives the most recent day from parquet.
    _gtgd_window_days = {0: 1, 7: 5, 30: 20}.get(_mf_days, max(1, _mf_days))
    _gtgd_by_ticker = _compute_gtgd_by_window(_gtgd_window_days)

    # ── Fetch order_stats (BigOrder) cho top mã GTGD ─────────────────────
    _live_quotes = _batch_load_live_quotes(_warehouse_tickers_all)

    def _pick_gtgd(tk):
        """Warehouse-based GTGD for all windows (1D/5D/20D)."""
        return _gtgd_by_ticker.get(tk, 0)

    # Rank by GTGD → top 50 cho order_stats
    _gtgd_ranked = sorted(
        [(tk, _pick_gtgd(tk)) for tk in _warehouse_tickers_all],
        key=lambda x: x[1], reverse=True,
    )
    _top_50_tickers = tuple(tk for tk, _ in _gtgd_ranked[:50])

    with st.spinner("Đang tải dữ liệu Lệnh lớn (top 50 mã)..."):
        _order_data = _fetch_order_stats_batch(_top_50_tickers)

    # ── Compute per-stock scores ─────────────────────────────────────────
    _stock_rows = []
    for tk in _warehouse_tickers_all:
        nn_net = _nn_by_ticker.get(tk, 0)
        nn_bs = _nn_bs_by_ticker.get(tk, {})
        lq = _live_quotes.get(tk, {})
        od = _order_data.get(tk, {})
        industry = _ind_map.get(tk, "Khác")
        sector = _mf_sector(tk, industry)

        # Prefer order_stats buy/sell ratio (actual matched trades) over bid/ask depth
        buy_ratio = od.get("buy_sell_ratio", lq.get("buy_ratio", 0.5))

        _stock_rows.append({
            "ticker": tk,
            "industry": industry,
            "sector": sector,
            "price": lq.get("price", 0),
            "volume": lq.get("volume", 0),
            "gtgd": _pick_gtgd(tk),
            "nn_net": nn_net,
            "nn_buy": nn_bs.get("buy", 0),
            "nn_sell": nn_bs.get("sell", 0),
            "buy_ratio": buy_ratio,
            "big_order_score": od.get("big_order_score", 0),
            "has_order": bool(od),   # False = ngoài top-50 / fetch lỗi → hiện "—"
        })

    # Compute median |nn_net| for normalization
    _nn_abs = [abs(r["nn_net"]) for r in _stock_rows if r["nn_net"] != 0]
    _nn_median = float(np.median(_nn_abs)) if _nn_abs else 1.0

    for r in _stock_rows:
        r["score"] = _compute_money_flow_score(
            r["nn_net"], _nn_median, r["buy_ratio"], r["big_order_score"]
        )

    # ── Aggregate by sector ──────────────────────────────────────────────
    _sector_summary = {}
    for sec in _MF_SECTOR_ORDER:
        rows = [r for r in _stock_rows if r["sector"] == sec]
        if not rows:
            continue
        total_gtgd = sum(r["gtgd"] for r in rows)
        total_vol = sum(r["volume"] for r in rows)
        total_nn = sum(r["nn_net"] for r in rows)

        # Weighted avg score by GTGD
        if total_gtgd > 0:
            w_score = sum(r["score"] * r["gtgd"] for r in rows) / total_gtgd
        else:
            w_score = np.mean([r["score"] for r in rows]) if rows else 0

        # Weighted buy ratio
        if total_gtgd > 0:
            w_buy = sum(r["buy_ratio"] * r["gtgd"] for r in rows) / total_gtgd
        else:
            w_buy = 0.5

        _sector_summary[sec] = {
            "n_stocks": len(rows),
            "gtgd": total_gtgd,
            "volume": total_vol,
            "nn_net": total_nn,
            "buy_ratio": w_buy,
            "score": round(w_score, 1),
            "stocks": sorted(rows, key=lambda x: x["score"], reverse=True),
        }

    # ── KPI metrics ──────────────────────────────────────────────────────
    _total_nn = sum(s["nn_net"] for s in _sector_summary.values())
    _inflow_sectors = sum(1 for s in _sector_summary.values() if s["score"] > 10)
    _outflow_sectors = sum(1 for s in _sector_summary.values() if s["score"] < -10)
    _top_sector = max(_sector_summary.items(), key=lambda x: x[1]["score"], default=("—", {}))
    _bot_sector = min(_sector_summary.items(), key=lambda x: x[1]["score"], default=("—", {}))

    kc1, kc2, kc3, kc4 = st.columns(4)
    with kc1:
        _nn_color = "#10b981" if _total_nn >= 0 else "#ef4444"
        _nn_sign = "+" if _total_nn > 0 else ""
        st.markdown(
            f'<div class="metric-card"><div class="label">NN ròng ({_mf_window})</div>'
            f'<div class="value" style="color:{_nn_color}">{_nn_sign}{_total_nn:,.0f} tỷ</div>'
            f'<div class="sub">{len(_nn_by_ticker)} mã / {_nn_record_count} records</div></div>',
            unsafe_allow_html=True)
    with kc2:
        st.markdown(
            f'<div class="metric-card"><div class="label">Ngành có tiền VÀO</div>'
            f'<div class="value" style="color:#10b981">{_inflow_sectors}</div>'
            f'<div class="sub">/ {len(_sector_summary)} ngành</div></div>',
            unsafe_allow_html=True)
    with kc3:
        st.markdown(
            f'<div class="metric-card"><div class="label">Ngành có tiền RA</div>'
            f'<div class="value" style="color:#ef4444">{_outflow_sectors}</div>'
            f'<div class="sub">/ {len(_sector_summary)} ngành</div></div>',
            unsafe_allow_html=True)
    with kc4:
        _top_name = _top_sector[0]
        _top_score = _top_sector[1].get("score", 0)
        st.markdown(
            f'<div class="metric-card"><div class="label">Ngành mạnh nhất</div>'
            f'<div class="value" style="color:#10b981">{_MF_SECTOR_ICONS.get(_top_name, "")} '
            f'{_top_name}</div>'
            f'<div class="sub">Score: {_top_score:+.0f}</div></div>',
            unsafe_allow_html=True)

    st.markdown("")

    # ── Sector summary table (Tầng 1) ────────────────────────────────────
    _table_html = (
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        '<tr style="border-bottom:2px solid #374151">'
        '<th style="text-align:left;padding:8px 6px;color:#9ca3af">Ngành</th>'
        '<th style="text-align:right;padding:8px 6px;color:#9ca3af">Mã</th>'
        f'<th style="text-align:right;padding:8px 6px;color:#9ca3af">GTGD {_mf_window} (tỷ)</th>'
        '<th style="text-align:right;padding:8px 6px;color:#9ca3af">Vol (tr CP)</th>'
        f'<th style="text-align:right;padding:8px 6px;color:#9ca3af">NN ròng {_mf_window} (tỷ)</th>'
        '<th style="text-align:right;padding:8px 6px;color:#9ca3af">Buy/Sell</th>'
        '<th style="text-align:center;padding:8px 6px;color:#9ca3af">Dòng tiền</th>'
        '</tr>'
    )

    for i, sec in enumerate(_MF_SECTOR_ORDER):
        if sec not in _sector_summary:
            continue
        s = _sector_summary[sec]
        icon = _MF_SECTOR_ICONS.get(sec, "")
        _, name_color = _score_label(s["score"])
        nn_color = "#10b981" if s["nn_net"] >= 0 else "#ef4444"
        nn_sign = "+" if s["nn_net"] > 0 else ""
        buy_pct = s["buy_ratio"] * 100
        buy_color = "#10b981" if buy_pct > 55 else ("#ef4444" if buy_pct < 45 else "#9ca3af")
        bg = "#0d1117" if i % 2 == 0 else "#111827"

        _table_html += (
            f'<tr style="background:{bg};border-bottom:1px solid #1f2937">'
            f'<td style="padding:7px 6px;color:{name_color};font-weight:600">'
            f'{icon} {sec}</td>'
            f'<td style="padding:7px 6px;text-align:right;color:#d1d5db">{s["n_stocks"]}</td>'
            f'<td style="padding:7px 6px;text-align:right;color:#d1d5db">'
            f'{s["gtgd"]:,.0f}</td>'
            f'<td style="padding:7px 6px;text-align:right;color:#d1d5db">'
            f'{s["volume"]/1e6:,.1f}</td>'
            f'<td style="padding:7px 6px;text-align:right;color:{nn_color};font-weight:500">'
            f'{nn_sign}{s["nn_net"]:,.0f}</td>'
            f'<td style="padding:7px 6px;text-align:right;color:{buy_color}">'
            f'{buy_pct:.0f}/{100-buy_pct:.0f}</td>'
            f'<td style="padding:7px 6px;text-align:center">'
            f'{_score_bar_html(s["score"])}</td>'
            f'</tr>'
        )
    _table_html += '</table>'
    st.markdown(_table_html, unsafe_allow_html=True)

    st.markdown("")

    # ── Drill-down: chi tiết mã trong ngành (Tầng 2) ─────────────────────
    _available_sectors = [s for s in _MF_SECTOR_ORDER if s in _sector_summary]
    _selected_sector = st.selectbox(
        "Chi tiết ngành",
        _available_sectors,
        format_func=lambda s: (
            f"{_MF_SECTOR_ICONS.get(s, '')} {s} ({_sector_summary[s]['n_stocks']} mã)"
        ),
        key="mf_drill",
        help=(
            "Chọn 1 ngành để xem **từng mã** bên trong.\n\n"
            "Mỗi mã hiển thị:\n"
            "- **Score** riêng (NN ròng + Buy/Sell)\n"
            "- **Vai trò**: ★ Kéo VÀO/RA (mã đóng góp >25% NN ngành), "
            "↔ Ngược dòng (mã đi ngược chiều ngành)\n\n"
            "Mã được sort theo score giảm dần — mã có tiền vào mạnh nhất "
            "nằm trên cùng."
        ),
    )

    if _selected_sector and _selected_sector in _sector_summary:
        _sec = _sector_summary[_selected_sector]
        stocks = _sec["stocks"]

        _, _sec_color = _score_label(_sec["score"])
        st.markdown(
            f"**{_MF_SECTOR_ICONS.get(_selected_sector, '')} {_selected_sector}** — "
            f"Score: <span style='color:{_sec_color};font-weight:700'>"
            f"{_sec['score']:+.0f}</span> | "
            f"NN ròng: {_sec['nn_net']:+,.0f} tỷ | "
            f"GTGD: {_sec['gtgd']:,.0f} tỷ",
            unsafe_allow_html=True,
        )

        # Detail table
        _det_html = (
            '<table style="width:100%;border-collapse:collapse;font-size:12px;'
            'margin-top:8px">'
            '<tr style="border-bottom:2px solid #374151">'
            '<th style="text-align:left;padding:6px;color:#9ca3af">Mã</th>'
            '<th style="text-align:left;padding:6px;color:#9ca3af">Ngành gốc</th>'
            '<th style="text-align:right;padding:6px;color:#9ca3af">Giá</th>'
            f'<th style="text-align:right;padding:6px;color:#9ca3af">'
            f'GTGD {_mf_window} (tỷ)</th>'
            f'<th style="text-align:right;padding:6px;color:#9ca3af">'
            f'NN Mua {_mf_window}</th>'
            f'<th style="text-align:right;padding:6px;color:#9ca3af">'
            f'NN Bán {_mf_window}</th>'
            f'<th style="text-align:right;padding:6px;color:#9ca3af">'
            f'NN Ròng {_mf_window}</th>'
            '<th style="text-align:right;padding:6px;color:#9ca3af">Buy/Sell</th>'
            '<th style="text-align:right;padding:6px;color:#9ca3af">Lệnh lớn</th>'
            '<th style="text-align:right;padding:6px;color:#9ca3af">Score</th>'
            '<th style="text-align:center;padding:6px;color:#9ca3af">Dòng tiền</th>'
            '<th style="text-align:center;padding:6px;color:#9ca3af">Vai trò</th>'
            '</tr>'
        )

        # Determine which stocks "pull" the sector
        _sec_nn_total = abs(_sec["nn_net"]) if _sec["nn_net"] != 0 else 1
        for j, stk in enumerate(stocks[:50]):
            s_label, s_color = _score_label(stk["score"])
            nn_color = "#10b981" if stk["nn_net"] >= 0 else "#ef4444"
            nn_sign = "+" if stk["nn_net"] > 0 else ""
            buy_pct = stk["buy_ratio"] * 100
            buy_color = "#10b981" if buy_pct > 55 else (
                "#ef4444" if buy_pct < 45 else "#9ca3af")
            bg = "#0d1117" if j % 2 == 0 else "#111827"

            # Role: does this stock pull the sector?
            nn_contribution = abs(stk["nn_net"]) / _sec_nn_total * 100
            if nn_contribution > 25 and abs(stk["score"]) > 20:
                if stk["score"] > 0:
                    role = '<span style="color:#10b981;font-weight:700">★ Kéo VÀO</span>'
                else:
                    role = '<span style="color:#ef4444;font-weight:700">★ Kéo RA</span>'
            elif abs(stk["score"]) > 30 and (
                (stk["score"] > 0) != (_sec["score"] > 0)
            ):
                role = '<span style="color:#f59e0b">↔ Ngược dòng</span>'
            else:
                role = '<span style="color:#4b5563">—</span>'

            _nn_buy = stk.get("nn_buy", 0)
            _nn_sell = stk.get("nn_sell", 0)
            # Lệnh lớn: only top-50 GTGD tickers have order_stats → others show "—"
            # (a literal 0 there is "no data", not "order size == average").
            _bo = stk.get("big_order_score", 0)
            if stk.get("has_order"):
                _bo_color = "#10b981" if _bo > 10 else ("#ef4444" if _bo < -10 else "#9ca3af")
                _bo_txt = f"{_bo:+.0f}"
            else:
                _bo_color, _bo_txt = "#4b5563", "—"
            _det_html += (
                f'<tr style="background:{bg};border-bottom:1px solid #1f2937">'
                f'<td style="padding:5px 6px;color:#60a5fa;font-weight:600">'
                f'{stk["ticker"]}</td>'
                f'<td style="padding:5px 6px;color:#9ca3af;font-size:11px">'
                f'{stk["industry"]}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:#d1d5db">'
                f'{stk["price"]:,.1f}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:#d1d5db">'
                f'{stk["gtgd"]:,.0f}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:#10b981">'
                f'{_nn_buy:,.0f}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:#ef4444">'
                f'{_nn_sell:,.0f}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:{nn_color};'
                f'font-weight:500">{nn_sign}{stk["nn_net"]:,.0f}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:{buy_color}">'
                f'{buy_pct:.0f}/{100-buy_pct:.0f}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:{_bo_color}">'
                f'{_bo_txt}</td>'
                f'<td style="padding:5px 6px;text-align:right;color:{s_color};'
                f'font-weight:600">{stk["score"]:+.0f}</td>'
                f'<td style="padding:5px 6px;text-align:center">'
                f'{_score_bar_html(stk["score"])}</td>'
                f'<td style="padding:5px 6px;text-align:center">{role}</td>'
                f'</tr>'
            )

        _det_html += '</table>'
        st.markdown(_det_html, unsafe_allow_html=True)

    # ── F4: Foreign flow deep dive — top mã + sector chart ───────────────
    st.markdown("---")
    st.markdown("#### 🔍 Khối Ngoại Chi Tiết")

    if _nn_raw.empty:
        st.info("Chưa có dữ liệu NN ròng. Bấm **🗑 Xoá cache** trong sidebar rồi thử lại.")
    else:
        # Build per-stock ranked list for selected window
        _nn_net   = _nn_by_ticker          # {symbol: net_tỷ} from selected window
        _nn_bs    = _nn_bs_by_ticker       # {symbol: {buy, sell}}

        # Merge into flat rows, enrich with sector
        _deep_rows = []
        for sym, net in _nn_net.items():
            bs   = _nn_bs.get(sym, {})
            ind  = _ind_map.get(sym, {}) if isinstance(_ind_map.get(sym), dict) else {}
            sec  = _mf_sector(sym, _ind_map.get(sym, "")) if sym in _ind_map else "—"
            _deep_rows.append({
                "Mã": sym,
                "Ngành": sec,
                "Mua (tỷ)": bs.get("buy", 0),
                "Bán (tỷ)": bs.get("sell", 0),
                "Ròng (tỷ)": net,
            })

        if _deep_rows:
            import pandas as _pd2
            _df_deep = _pd2.DataFrame(_deep_rows)
            _df_deep = _df_deep[_df_deep["Mua (tỷ)"] + _df_deep["Bán (tỷ)"] > 0]

            # ── Top mua ròng / bán ròng ──────────────────────────────────
            _top_col, _bot_col = st.columns(2)

            _top10_buy = _df_deep.nlargest(10, "Ròng (tỷ)")
            _top10_sell = _df_deep.nsmallest(10, "Ròng (tỷ)")

            with _top_col:
                st.markdown("**🟢 Top 10 mã mua ròng**")
                if not _top10_buy.empty and _top10_buy["Ròng (tỷ)"].max() > 0:
                    st.dataframe(
                        _top10_buy[["Mã", "Ngành", "Mua (tỷ)", "Bán (tỷ)", "Ròng (tỷ)"]].reset_index(drop=True),
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Ròng (tỷ)": st.column_config.NumberColumn(format="%.1f"),
                            "Mua (tỷ)":  st.column_config.NumberColumn(format="%.1f"),
                            "Bán (tỷ)":  st.column_config.NumberColumn(format="%.1f"),
                        },
                    )
                else:
                    st.caption("Không có mã mua ròng trong khung này.")

            with _bot_col:
                st.markdown("**🔴 Top 10 mã bán ròng**")
                if not _top10_sell.empty and _top10_sell["Ròng (tỷ)"].min() < 0:
                    st.dataframe(
                        _top10_sell[["Mã", "Ngành", "Mua (tỷ)", "Bán (tỷ)", "Ròng (tỷ)"]].reset_index(drop=True),
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Ròng (tỷ)": st.column_config.NumberColumn(format="%.1f"),
                            "Mua (tỷ)":  st.column_config.NumberColumn(format="%.1f"),
                            "Bán (tỷ)":  st.column_config.NumberColumn(format="%.1f"),
                        },
                    )
                else:
                    st.caption("Không có mã bán ròng trong khung này.")

            # ── Cumulative NN ròng theo ngành — bar chart ─────────────────
            _sec_net: dict[str, float] = {}
            for sym, net in _nn_net.items():
                sec = _mf_sector(sym, _ind_map.get(sym, "")) if sym in _ind_map else "—"
                _sec_net[sec] = _sec_net.get(sec, 0.0) + net

            # Remove unknown/empty sector and sort by value
            _sec_net.pop("—", None)
            _sec_items = sorted(_sec_net.items(), key=lambda x: x[1], reverse=True)

            if _sec_items:
                st.markdown(f"**📊 NN ròng theo ngành — {_mf_window}**")
                try:
                    import plotly.graph_objects as _go
                    _secs   = [s for s, _ in _sec_items]
                    _vals   = [v for _, v in _sec_items]
                    _colors = ["#22c55e" if v >= 0 else "#ef4444" for v in _vals]
                    _fig = _go.Figure(_go.Bar(
                        x=_secs, y=_vals,
                        marker_color=_colors,
                        text=[f"{v:+.1f}" for v in _vals],
                        textposition="outside",
                    ))
                    _fig.update_layout(
                        height=300,
                        margin=dict(l=0, r=0, t=10, b=60),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        font_color="#e5e7eb",
                        yaxis=dict(
                            title="tỷ VND",
                            showgrid=True,
                            gridcolor="#374151",
                            zeroline=True,
                            zerolinecolor="#6b7280",
                        ),
                        xaxis=dict(showgrid=False, tickangle=-30),
                    )
                    st.plotly_chart(_fig, use_container_width=True)
                except ImportError:
                    # Fallback: simple dataframe table
                    _df_sec = _pd2.DataFrame(_sec_items, columns=["Ngành", "NN ròng (tỷ)"])
                    st.dataframe(_df_sec, hide_index=True, use_container_width=True)
        else:
            st.caption("Chưa có data NN ròng cho window này.")

    # ── Real-time mode ───────────────────────────────────────────────────
    if _mf_live_on and WSS_AVAILABLE:
        st.markdown("---")
        st.markdown("#### 🔴 Live Money Flow (real-time)")

        @st.fragment(run_every=15)
        def _live_money_flow_fragment():
            _live_d = Path("data_warehouse/_live")
            if not _live_d.exists():
                st.caption("⏳ Chưa có live data — bật Live Mode trong tab Phân tích")
                return

            quote_files = list(_live_d.glob("quote_*.json"))
            if not quote_files:
                st.caption("⏳ Chờ WSS poll data...")
                return

            ind_map = _load_industry_map()
            sector_live = {}

            for qf in quote_files:
                try:
                    tk = qf.stem.replace("quote_", "")
                    if not _is_stock(tk) or tk not in ind_map:
                        continue
                    q = json.loads(qf.read_text(encoding="utf-8"))
                    price = float(q.get("price", 0) or 0)
                    if price <= 0:
                        continue
                    if price > 500:
                        price /= 1000
                    vol = float(q.get("volume", 0) or 0)
                    gtgd = price * vol / 1e6

                    # Buy/Sell — try volume_profile first, fall back to bid/ask depth
                    vp = q.get("volume_profile", [])
                    total_buy = sum(float(lv.get("buy_vol", 0) or 0) for lv in vp)
                    total_sell = sum(float(lv.get("sell_vol", 0) or 0) for lv in vp)
                    total_vs = total_buy + total_sell
                    if total_vs > 0:
                        buy_r = total_buy / total_vs
                    else:
                        # Fallback: bid/ask depth from price_board
                        bids = q.get("bids", [])
                        asks = q.get("asks", [])
                        bv = sum(float(b.get("volume", 0) or 0) for b in bids if isinstance(b, dict))
                        av = sum(float(a.get("volume", 0) or 0) for a in asks if isinstance(a, dict))
                        buy_r = bv / (bv + av) if (bv + av) > 0 else 0.5

                    sector = _mf_sector(tk, ind_map[tk])
                    if sector not in sector_live:
                        sector_live[sector] = {
                            "gtgd": 0, "vol": 0,
                            "buy_total": 0, "sell_total": 0, "count": 0,
                        }
                    sl = sector_live[sector]
                    sl["gtgd"] += gtgd
                    sl["vol"] += vol
                    sl["buy_total"] += total_buy
                    sl["sell_total"] += total_sell
                    sl["count"] += 1
                except Exception:
                    continue

            if not sector_live:
                st.caption("⏳ Đang chờ data...")
                return

            # Build compact live table
            _lt = (
                '<table style="width:100%;border-collapse:collapse;font-size:12px">'
                '<tr style="border-bottom:2px solid #374151">'
                '<th style="text-align:left;padding:5px;color:#9ca3af">Ngành</th>'
                '<th style="text-align:right;padding:5px;color:#9ca3af">Mã</th>'
                '<th style="text-align:right;padding:5px;color:#9ca3af">GTGD</th>'
                '<th style="text-align:right;padding:5px;color:#9ca3af">Buy/Sell</th>'
                '<th style="text-align:center;padding:5px;color:#9ca3af">Áp lực</th>'
                '</tr>'
            )
            for idx, sec in enumerate(_MF_SECTOR_ORDER):
                if sec not in sector_live:
                    continue
                sl = sector_live[sec]
                total_vs = sl["buy_total"] + sl["sell_total"]
                buy_pct = (sl["buy_total"] / total_vs * 100) if total_vs > 0 else 50
                sell_pct = 100 - buy_pct
                buy_color = "#10b981" if buy_pct > 55 else (
                    "#ef4444" if buy_pct < 45 else "#9ca3af")

                # Simple score from buy/sell only (no NN in realtime)
                live_score = (buy_pct - 50) * 2
                bg = "#0d1117" if idx % 2 == 0 else "#111827"
                _lt += (
                    f'<tr style="background:{bg};border-bottom:1px solid #1f2937">'
                    f'<td style="padding:4px 5px;color:#d1d5db">'
                    f'{_MF_SECTOR_ICONS.get(sec, "")} {sec}</td>'
                    f'<td style="padding:4px 5px;text-align:right;color:#9ca3af">'
                    f'{sl["count"]}</td>'
                    f'<td style="padding:4px 5px;text-align:right;color:#d1d5db">'
                    f'{sl["gtgd"]:,.0f} tỷ</td>'
                    f'<td style="padding:4px 5px;text-align:right;color:{buy_color}">'
                    f'{buy_pct:.0f}/{sell_pct:.0f}</td>'
                    f'<td style="padding:4px 5px;text-align:center">'
                    f'{_score_bar_html(live_score)}</td>'
                    f'</tr>'
                )
            _lt += '</table>'
            st.markdown(_lt, unsafe_allow_html=True)
            st.caption(
                f"🔄 Cập nhật mỗi 15s | "
                f"{sum(s['count'] for s in sector_live.values())} mã | "
                f"Chỉ dựa trên Buy/Sell volume (không có NN ròng real-time)"
            )

        _live_money_flow_fragment()
