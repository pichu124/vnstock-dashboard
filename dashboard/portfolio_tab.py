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
