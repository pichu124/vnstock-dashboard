"""
Portfolio tab — 💼 position tracker with live-price P&L.

Rendered from ``vnstock_dashboard.py`` via the dispatch pattern
documented in ``docs/REFACTOR_PLAN.md``. All Streamlit imports happen
inside ``render_portfolio_tab`` so the module stays importable for unit
tests without requiring the Streamlit runtime.

State
-----
Positions are persisted to ``<warehouse>/_meta/portfolio.json`` as a
list of ``{ticker, quantity, buy_price, buy_date}`` dicts. The
``_save_portfolio`` helper writes atomically via a ``.pid.tmp`` file.

Live price resolution
---------------------
For each position, the tab tries (in order):
  1. ``<warehouse>/_live/quote_{TICKER}.json`` — WSS realtime snapshot
  2. Newest close in ``<warehouse>/prices/ticker={TICKER}/year=*/*.parquet``

If neither yields a price > 0, the row still renders but shows ``—`` for
current price and contributes 0 to the portfolio total — intentional
so a missing live feed doesn't silently zero-out the P&L.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_WAREHOUSE = Path("data_warehouse")


def _portfolio_path(warehouse: Path) -> Path:
    return warehouse / "_meta" / "portfolio.json"


def _load_portfolio(warehouse: Path) -> list[dict]:
    path = _portfolio_path(warehouse)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save_portfolio(warehouse: Path, positions: list[dict]) -> None:
    path = _portfolio_path(warehouse)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(positions, indent=2, ensure_ascii=False))
        os.replace(str(tmp), str(path))
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass


def _live_quote(ticker: str, warehouse: Path) -> dict | None:
    path = warehouse / "_live" / f"quote_{ticker.upper()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _warehouse_last_close(ticker: str, warehouse: Path) -> float:
    import pyarrow.parquet as pq
    ticker_dir = warehouse / "prices" / f"ticker={ticker}"
    if not ticker_dir.exists():
        return 0.0
    try:
        for year_dir in sorted(ticker_dir.iterdir(), reverse=True):
            if not year_dir.is_dir():
                continue
            for pq_file in sorted(year_dir.glob("*.parquet"), reverse=True):
                tbl = pq.read_table(str(pq_file), columns=["close"]).to_pandas()
                if not tbl.empty:
                    return float(tbl["close"].iloc[-1])
    except Exception:
        return 0.0
    return 0.0


def render_portfolio_tab(warehouse: Path | str = DEFAULT_WAREHOUSE) -> None:
    """Render the Portfolio tab. Lazy imports Streamlit."""
    try:
        import streamlit as st
    except ImportError:
        print("[portfolio_tab] streamlit not available")
        return

    warehouse = Path(warehouse)
    st.markdown("### 💼 Danh mục đầu tư")

    positions = _load_portfolio(warehouse)

    with st.sidebar:
        st.markdown("### 💼 Portfolio")

        with st.expander("➕ Thêm vị thế", expanded=not bool(positions)):
            _pf_ticker = st.text_input("Mã", placeholder="VCB",
                                        key="pf_ticker").upper().strip()
            _pf_qty = st.number_input("Số lượng (cp)", min_value=0, value=100,
                                       step=100, key="pf_qty")
            _pf_price = st.number_input("Giá mua (VND)", min_value=0.0,
                                         value=0.0, step=100.0,
                                         format="%.0f", key="pf_price")
            _pf_date = st.date_input("Ngày mua", key="pf_date")
            if st.button("✅ Thêm", key="pf_add", use_container_width=True):
                if _pf_ticker and _pf_qty > 0 and _pf_price > 0:
                    positions.append({
                        "ticker": _pf_ticker,
                        "quantity": _pf_qty,
                        "buy_price": _pf_price,
                        "buy_date": str(_pf_date),
                    })
                    _save_portfolio(warehouse, positions)
                    st.rerun()

        if positions:
            st.caption(f"{len(positions)} vị thế")
            if st.button("🗑 Xoá tất cả", key="pf_clear",
                          use_container_width=True):
                _save_portfolio(warehouse, [])
                st.rerun()

    if not positions:
        st.info("Chưa có vị thế nào. Thêm ở sidebar → Portfolio → ➕ Thêm vị thế")
        return

    total_invested = 0.0
    total_current = 0.0
    rows: list[dict] = []

    for i, pos in enumerate(positions):
        ticker = pos["ticker"]
        qty = pos["quantity"]
        buy_price = pos["buy_price"]
        buy_date = pos.get("buy_date", "")

        invested = qty * buy_price
        total_invested += invested

        current_price = 0.0
        q = _live_quote(ticker, warehouse)
        if q and float(q.get("price", 0)) > 0:
            current_price = float(q["price"])
        else:
            current_price = _warehouse_last_close(ticker, warehouse)

        current_val = qty * current_price if current_price > 0 else 0
        total_current += current_val
        pnl = current_val - invested
        pnl_pct = (pnl / invested * 100) if invested > 0 else 0

        rows.append({
            "ticker": ticker,
            "qty": qty,
            "buy_price": buy_price,
            "buy_date": buy_date,
            "current_price": current_price,
            "invested": invested,
            "current_val": current_val,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "idx": i,
        })

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    _pnl_color = "#10b981" if total_pnl >= 0 else "#ef4444"
    _pnl_sign = "+" if total_pnl >= 0 else ""

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="metric-card"><div class="label">Vốn đầu tư</div>'
            f'<div class="value">{total_invested:,.0f}</div>'
            f'<div class="sub">VND</div></div>',
            unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div class="metric-card"><div class="label">Giá trị hiện tại</div>'
            f'<div class="value">{total_current:,.0f}</div>'
            f'<div class="sub">VND</div></div>',
            unsafe_allow_html=True)
    with c3:
        st.markdown(
            f'<div class="metric-card"><div class="label">Lãi/Lỗ</div>'
            f'<div class="value" style="color:{_pnl_color}">'
            f'{_pnl_sign}{total_pnl:,.0f}</div>'
            f'<div class="sub">VND</div></div>',
            unsafe_allow_html=True)
    with c4:
        st.markdown(
            f'<div class="metric-card"><div class="label">% Lãi/Lỗ</div>'
            f'<div class="value" style="color:{_pnl_color}">'
            f'{_pnl_sign}{total_pnl_pct:.2f}%</div>'
            f'<div class="sub">tổng danh mục</div></div>',
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    _th = ("background:#111827;color:#6b7280;font-size:10px;font-weight:500;"
           "text-transform:uppercase;letter-spacing:0.05em;padding:6px 10px;"
           "border-bottom:2px solid #1f2937;text-align:right;"
           "font-family:'IBM Plex Sans',sans-serif;")
    _td = ("padding:5px 10px;border-bottom:1px solid #1a2234;"
           "font-size:12px;font-family:'IBM Plex Mono',monospace;text-align:right;")

    _rows_html = ""
    for r in sorted(rows, key=lambda x: x["pnl"], reverse=True):
        _pc = "#10b981" if r["pnl"] >= 0 else "#ef4444"
        _ps = "+" if r["pnl"] >= 0 else ""
        _bg = "#0d1117"
        _cur_cell = (f"{r['current_price']:,.0f}"
                     if r['current_price'] > 0 else "—")
        _rows_html += (
            f"<tr style='background:{_bg}'>"
            f"<td style='{_td}text-align:left;color:#60a5fa;font-weight:600'>{r['ticker']}</td>"
            f"<td style='{_td}color:#9ca3af'>{r['qty']:,}</td>"
            f"<td style='{_td}color:#9ca3af'>{r['buy_price']:,.0f}</td>"
            f"<td style='{_td}color:#e5e7eb'>{_cur_cell}</td>"
            f"<td style='{_td}color:#9ca3af'>{r['invested']:,.0f}</td>"
            f"<td style='{_td}color:#e5e7eb'>{r['current_val']:,.0f}</td>"
            f"<td style='{_td}color:{_pc};font-weight:600'>{_ps}{r['pnl']:,.0f}</td>"
            f"<td style='{_td}color:{_pc};font-weight:600'>{_ps}{r['pnl_pct']:.2f}%</td>"
            f"<td style='{_td}color:#9ca3af;font-size:10px'>{r['buy_date']}</td>"
            f"</tr>"
        )

    _tbl = (
        f"<div style='overflow-x:auto;border:1px solid #1f2937;border-radius:8px'>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"<thead><tr>"
        f"<th style='{_th}text-align:left'>Mã</th>"
        f"<th style='{_th}'>SL</th>"
        f"<th style='{_th}'>Giá mua</th>"
        f"<th style='{_th}'>Giá hiện tại</th>"
        f"<th style='{_th}'>Vốn</th>"
        f"<th style='{_th}'>GT hiện tại</th>"
        f"<th style='{_th}'>Lãi/Lỗ</th>"
        f"<th style='{_th}'>%</th>"
        f"<th style='{_th}'>Ngày mua</th>"
        f"</tr></thead>"
        f"<tbody>{_rows_html}</tbody></table></div>"
    )
    st.markdown(_tbl, unsafe_allow_html=True)

    # ── Net-worth curve — NAV danh mục vs VNINDEX (món DojoAgents 20/07) ──
    st.markdown("---")
    st.markdown("#### 📈 Giá trị danh mục theo thời gian (NAV)")
    try:
        from vnstock_networth import load_networth
        _nw = load_networth(warehouse)
        if not _nw or not _nw.get("nav_rebased"):
            st.caption("Chưa đủ dữ liệu giá trong kho để dựng đường NAV "
                       "(cần ≥ 2 phiên kể từ ngày mua sớm nhất).")
        else:
            try:
                import plotly.graph_objects as _go_nw
                _fig_nw = _go_nw.Figure()
                _fig_nw.add_trace(_go_nw.Scatter(
                    x=_nw["dates"], y=_nw["nav_rebased"],
                    name="Danh mục (NAV)",
                    line=dict(color="#60a5fa", width=2)))
                if _nw.get("index_rebased"):
                    _fig_nw.add_trace(_go_nw.Scatter(
                        x=_nw["dates"], y=_nw["index_rebased"],
                        name="VNINDEX",
                        line=dict(color="#94a3b8", width=1.5, dash="dash")))
                _fig_nw.update_layout(
                    height=320,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis=dict(title="Rebase 100"),
                    legend=dict(orientation="h", y=1.1),
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font=dict(color="#f1f5f9"),
                )
                st.plotly_chart(_fig_nw, use_container_width=True)
            except Exception:
                import pandas as _pd_nw
                _df_nw = _pd_nw.DataFrame(
                    {"Danh mục": _nw["nav_rebased"]},
                    index=_pd_nw.to_datetime(_nw["dates"]))
                if _nw.get("index_rebased"):
                    _df_nw["VNINDEX"] = _nw["index_rebased"]
                st.line_chart(_df_nw)

            _s_nw = _nw.get("stats") or {}
            _parts_nw = [f"{len(_nw['dates'])} phiên"]
            if _s_nw.get("cumulative_pct") is not None:
                _parts_nw.append(f"tích lũy {_s_nw['cumulative_pct']:+.1f}%")
            if _nw.get("index_rebased"):
                _parts_nw.append(
                    f"VNINDEX cùng kỳ {_nw['index_rebased'][-1] - 100:+.1f}%")
            if _s_nw.get("ann_vol_pct") is not None:
                _parts_nw.append(f"vol năm hóa {_s_nw['ann_vol_pct']:.1f}%")
            if _s_nw.get("sharpe") is not None:
                _parts_nw.append(f"Sharpe (rf=0) {_s_nw['sharpe']:.2f}")
            if _s_nw.get("max_drawdown_pct") is not None:
                _parts_nw.append(f"maxDD {_s_nw['max_drawdown_pct']:.1f}%")
            if _s_nw.get("calmar") is not None:
                _parts_nw.append(f"Calmar {_s_nw['calmar']:.2f}")
            st.caption("📊 " + " · ".join(_parts_nw))

            _notes_nw = ["Rebase 100 tại ngày đầu; vốn vị thế mua sau tính "
                         "như tiền mặt (0%) tới ngày mua — display-only."]
            if _nw.get("skipped_days"):
                _notes_nw.append(f"Bỏ {_nw['skipped_days']} phiên thiếu giá.")
            if _nw.get("excluded"):
                _notes_nw.append("Loại mã không có dữ liệu giá: "
                                 + ", ".join(_nw["excluded"]) + ".")
            st.caption(" ".join(_notes_nw))
    except Exception as _e_nw:
        st.caption(f"NAV curve không khả dụng: {_e_nw}")

    # ── F7: Sector Exposure ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🏗 Phân bổ theo ngành")
    try:
        import plotly.graph_objects as go
        from vnstock_dashboard import _load_industry_map, _get_sector, SECTOR_ICONS
        from vnstock_vn30_weights import compute_vn30_sector_weights, cache_metadata

        _ind_map = _load_industry_map()

        # Dynamic VN30 benchmark — market-cap weighted if data available,
        # else equal-weight by ticker count, else hardcoded fallback.
        _VN30_BENCH = compute_vn30_sector_weights()
        _bench_meta = cache_metadata() or {}

        # Aggregate portfolio current value by sector
        _sector_val: dict[str, float] = {}
        _sector_pnl: dict[str, float] = {}
        _unmapped: list[str] = []
        for r in rows:
            _pri_ind = _ind_map.get(r["ticker"], "")
            _sec = _get_sector(_pri_ind) if _pri_ind else "Khác"
            if not _pri_ind:
                _unmapped.append(r["ticker"])
            _val = r["current_val"] if r["current_val"] > 0 else r["invested"]
            _sector_val[_sec] = _sector_val.get(_sec, 0.0) + _val
            _sector_pnl[_sec] = _sector_pnl.get(_sec, 0.0) + r["pnl"]

        _total_val = sum(_sector_val.values()) or 1.0
        _sector_pct = {k: v / _total_val * 100 for k, v in _sector_val.items()}
        _sectors_sorted = sorted(_sector_pct.items(), key=lambda x: x[1], reverse=True)

        if not _sectors_sorted:
            st.info("Chưa có dữ liệu ngành.")
        else:
            _fc1, _fc2 = st.columns([3, 2])

            with _fc1:
                # Horizontal bar: portfolio % vs VN30 benchmark
                _names  = [f"{SECTOR_ICONS.get(s,'•')} {s}" for s, _ in _sectors_sorted]
                _port   = [pct for _, pct in _sectors_sorted]
                _bench  = [_VN30_BENCH.get(s, 0.0) for s, _ in _sectors_sorted]
                _delta  = [p - b for p, b in zip(_port, _bench)]
                _bar_colors = ["#22c55e" if d >= 0 else "#ef4444" for d in _delta]

                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    y=_names, x=_port,
                    orientation="h",
                    name="Danh mục",
                    marker_color="#60a5fa",
                    opacity=0.85,
                ))
                fig_bar.add_trace(go.Bar(
                    y=_names, x=_bench,
                    orientation="h",
                    name="VN30 benchmark",
                    marker_color="#475569",
                    opacity=0.5,
                ))
                fig_bar.update_layout(
                    title="Danh mục vs VN30 Benchmark (%)",
                    barmode="overlay",
                    xaxis=dict(title="%", ticksuffix="%"),
                    height=max(280, len(_names) * 38),
                    margin=dict(l=0, r=0, t=40, b=0),
                    legend=dict(orientation="h", y=1.12),
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font=dict(color="#f1f5f9"),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

            with _fc2:
                # Pie chart: portfolio allocation
                _pie_labels = [f"{SECTOR_ICONS.get(s,'•')} {s}" for s, _ in _sectors_sorted]
                _pie_vals   = [pct for _, pct in _sectors_sorted]
                fig_pie = go.Figure(go.Pie(
                    labels=_pie_labels,
                    values=_pie_vals,
                    hole=0.45,
                    textinfo="percent",
                    hovertemplate="%{label}: %{value:.1f}%<extra></extra>",
                    marker=dict(colors=[
                        "#3b82f6","#22c55e","#f59e0b","#ef4444","#8b5cf6",
                        "#06b6d4","#ec4899","#84cc16","#f97316","#14b8a6",
                        "#a78bfa","#fb7185","#fbbf24","#34d399","#94a3b8",
                    ]),
                ))
                fig_pie.update_layout(
                    title="Tỷ trọng danh mục",
                    height=max(280, len(_names) * 38),
                    margin=dict(l=0, r=0, t=40, b=10),
                    legend=dict(font=dict(size=10)),
                    plot_bgcolor="#0e1117",
                    paper_bgcolor="#0e1117",
                    font=dict(color="#f1f5f9"),
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            # Overweight / underweight summary table
            _tbl_rows = []
            for s, pct in _sectors_sorted:
                _bench_pct = _VN30_BENCH.get(s, 0.0)
                _diff = pct - _bench_pct
                _pnl_s = _sector_pnl.get(s, 0.0)
                _tbl_rows.append({
                    "Ngành": f"{SECTOR_ICONS.get(s,'•')} {s}",
                    "Danh mục %": round(pct, 1),
                    "VN30 %": round(_bench_pct, 1),
                    "Lệch (pp)": round(_diff, 1),
                    "Lãi/Lỗ (VND)": int(_pnl_s),
                })
            import pandas as _pd
            _df_exp = _pd.DataFrame(_tbl_rows)

            def _color_diff(val):
                if val > 2:
                    return "color: #22c55e"
                elif val < -2:
                    return "color: #ef4444"
                return "color: #94a3b8"

            st.dataframe(
                _df_exp.style.applymap(_color_diff, subset=["Lệch (pp)"]),
                use_container_width=True,
                hide_index=True,
            )
            _mode_label = {
                "market_cap": "🏛 market-cap weighted",
                "equal":      "⚖️ equal-weight (theo số mã)",
            }.get(_bench_meta.get("mode", ""), "⚠️ hardcoded fallback")
            _upd_at = (_bench_meta.get("updated_at") or "")[:10]
            st.caption(
                f"📊 VN30 benchmark: {_mode_label} · {_bench_meta.get('n_tickers','?')} mã"
                + (f" · cập nhật {_upd_at}" if _upd_at else "")
                + ". Lệch (pp) > 0 = overweight, < 0 = underweight."
            )
            if _unmapped:
                st.caption(f"Không tra được ngành: {', '.join(set(_unmapped))} — xếp vào 'Khác'.")

    except Exception as _e7:
        st.caption(f"Sector exposure không khả dụng: {_e7}")

    st.markdown("<br>", unsafe_allow_html=True)
    _options = ["—"] + [
        f"{r['ticker']} ({r['qty']} cp @ {r['buy_price']:,.0f})"
        for r in rows
    ]
    _del_idx = st.selectbox("Xoá vị thế", options=_options, key="pf_del_select")
    if _del_idx != "—" and st.button("🗑 Xoá vị thế này", key="pf_del_btn"):
        _del_i = _options.index(_del_idx) - 1   # -1 because of the "—" sentinel
        positions.pop(rows[_del_i]["idx"])
        _save_portfolio(warehouse, positions)
        st.rerun()
