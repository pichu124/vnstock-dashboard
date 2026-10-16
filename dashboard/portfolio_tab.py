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
``_save_portfolio`` writes atomically via ``vnstock_parquet_io.write_json_atomic``
and RAISES on failure. A corrupt file is NOT read as ``[]``: the tab shows
``st.error`` and hides every write action — otherwise "Thêm" would overwrite
the whole portfolio with ``[] + 1`` and Dropbox would push that to the other
machine.

Live price resolution
---------------------
``resolve_current_price`` (FIX 2026-07-20 — bug user bắt: quote WSS cũ
đóng băng giá SSI 26,650 trong khi kho đã có bar 20/07 = 22,700):
nguồn có NGÀY DATA mới hơn thắng giữa
  1. ``<warehouse>/_live/quote_{TICKER}.json`` — WSS snapshot (ngày CHỈ từ
     field ``time``; thiếu time → bỏ nguồn, mtime không tin được)
  2. bar MỚI NHẤT THEO THỜI GIAN trong kho parquet (gộp mọi file — Dropbox
     conflicted copy — qua ``vnstock_networth._close_series``)
cùng ngày → live (trong phiên tươi hơn close EOD); giá NEO về đơn vị
buy_price của user (kho trộn VND thô/nghìn đồng per-bar): kho neo bằng
close ≤ buy_date, quote neo qua close kho. Bảng hiện ngày·nguồn cạnh giá
+ tripwire ⚠ khi %L/L ngay trong ngày mua vượt xa mọi biên độ phiên hợp
lệ (nghi lệch đơn vị 1000× — ``_unit_suspect``).

If neither yields a price > 0, the row still renders but shows ``—`` for
current price and contributes 0 to the portfolio total — intentional
so a missing live feed doesn't silently zero-out the P&L.
"""

from __future__ import annotations

import json
from pathlib import Path

from vnstock_parquet_io import write_json_atomic


DEFAULT_WAREHOUSE = Path("data_warehouse")


def _portfolio_path(warehouse: Path) -> Path:
    return warehouse / "_meta" / "portfolio.json"


def _load_portfolio(warehouse: Path) -> list[dict]:
    """Thiếu file ⇒ ``[]`` (hợp lệ). File hỏng/sai dạng/không đọc được ⇒ raise
    (OSError/ValueError) — caller phải chặn ghi, không coi là danh mục rỗng."""
    path = _portfolio_path(warehouse)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not (isinstance(data, list) and all(isinstance(p, dict) for p in data)):
        raise ValueError("sai định dạng: cần list các vị thế dạng object "
                         "{ticker, quantity, buy_price, buy_date}")
    return data


def _save_portfolio(warehouse: Path, positions: list[dict]) -> None:
    write_json_atomic(positions, _portfolio_path(warehouse))


def _save_or_report(st, warehouse: Path, positions: list[dict]) -> bool:
    try:
        _save_portfolio(warehouse, positions)
    except OSError as e:
        st.error(f"Không ghi được `{_portfolio_path(warehouse)}`: {e} — danh mục trên đĩa "
                 "giữ nguyên.")
        return False
    return True


def _save_and_rerun(st, warehouse: Path, positions: list[dict]) -> None:
    if _save_or_report(st, warehouse, positions):
        st.rerun()


def _delete_position(st, warehouse: Path, idx: int) -> None:
    """``on_click`` của nút Xoá: chạy TRƯỚC lượt vẽ kế tiếp nên còn được trả selectbox
    ``pf_del_select`` về None — không thì nó giữ chỉ số cũ, giờ là lô KẾ TIẾP, và nút
    vẫn hiện: bấm đúp xoá luôn lô đó. Đọc LẠI file, không dùng bản chụp lúc vẽ (máy
    kia có thể vừa thêm lô); lỗi đọc/ghi ⇒ không ghi, giữ lựa chọn để bấm lại."""
    try:
        positions = _load_portfolio(warehouse)
    except (OSError, ValueError) as e:
        st.error(f"Không đọc lại được `{_portfolio_path(warehouse)}` ({e}) — chưa xoá gì.")
        return
    if _save_or_report(st, warehouse, [p for j, p in enumerate(positions) if j != idx]):
        st.session_state["pf_del_select"] = None


def _live_quote(ticker: str, warehouse: Path) -> dict | None:
    path = warehouse / "_live" / f"quote_{ticker.upper()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _quote_price_date(ticker: str, warehouse: Path) -> tuple[float, str] | None:
    """(price, iso_date) từ snapshot WSS — ngày CHỈ lấy từ field ``time``
    trong JSON (writer WSS luôn ghi). None khi thiếu file / giá rác / thiếu
    time: quote legacy/corrupt KHÔNG được lấy mtime file làm ngày data —
    Dropbox re-sync làm mới mtime khiến quote cũ đội lốt hôm nay và thắng
    bar kho mới (review 21/07)."""
    q = _live_quote(ticker, warehouse)
    if not q:
        return None
    try:
        price = float(q.get("price", 0) or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    day = str(q.get("time") or "")[:10]
    if len(day) != 10 or day[4:5] != "-":
        return None
    return price, day


def resolve_current_price(ticker: str, buy_price: float, buy_date: str,
                          warehouse: Path) -> tuple[float, str, str]:
    """Giá hiện tại cho 1 vị thế: (price, iso_date, source∈{live,kho}).

    FIX 2026-07-20 (bug user bắt trên máy thật): trước đây quote WSS thắng
    VÔ ĐIỀU KIỆN bất kể tuổi — file quote cũ đóng băng giá (SSI hiện 26,650
    trong khi kho đã có bar 20/07 = 22,700; cùng họ bug nn_flow_cache), và
    fallback kho lấy ``iloc[-1]`` của FILE ĐẦU THEO TÊN (không sort theo
    thời gian, không chuẩn hóa đơn vị). Nay:
    - nguồn có NGÀY DATA mới hơn thắng; cùng ngày → live (tươi hơn close);
    - bar kho = mới nhất THEO THỜI GIAN, gộp mọi file parquet (Dropbox
      conflicted copy) qua ``vnstock_networth._close_series``, cửa sổ đọc
      tính TỪ buy_date (``_span_days`` — cửa sổ cứng 400 ngày cũ làm mất
      close quanh ngày mua khi vị thế già hơn cửa sổ, review 21/07);
    - giá NEO về đơn vị buy_price (``_anchor_factor`` — kho trộn VND thô ↔
      nghìn đồng per-bar): kho neo bằng close ≤ buy_date; quote neo qua
      close kho cùng/kề phiên (KHÔNG neo thẳng vào buy_price tại ngày hôm
      nay — giá trôi >2× kể từ ngày mua làm residual bung khỏi _ANCHOR_TOL
      → factor kẹt 1.0 → 24.5 VND cho cổ phiếu 24,500, review 21/07);
      không có kho → fallback neo buy_price như cũ (hết mốc nào khác).
    (0.0, "", "") khi không nguồn nào dùng được.
    """
    try:
        from vnstock_networth import _anchor_factor, _close_series, _span_days
    except Exception:
        return 0.0, "", ""
    from datetime import date as _date
    warehouse = Path(warehouse)
    bp = float(buy_price or 0)
    bd = str(buy_date or "")[:10]

    candidates: list[tuple[str, int, float, str]] = []
    try:
        days = _span_days(bd, _date.today().isoformat())
        series = _close_series(ticker, days, prices_dir=warehouse / "prices")
    except Exception:
        series = []
    kho_ref = 0.0
    if series:
        dates = [d for d, _ in series]
        vals = [c for _, c in series]
        f = _anchor_factor(dates, vals, bd or dates[-1], bp) if bp > 0 else 1.0
        kho_ref = vals[-1] * f          # close kho mới nhất, ĐÃ về đơn vị buy_price
        candidates.append((dates[-1], 0, kho_ref, "kho"))
    q = _quote_price_date(ticker, warehouse)
    if q is not None:
        price, day = q
        if kho_ref > 0:
            f = _anchor_factor([day], [price], day, kho_ref)
        else:
            f = _anchor_factor([day], [price], day, bp) if bp > 0 else 1.0
        candidates.append((day, 1, price * f, "live"))
    if not candidates:
        return 0.0, "", ""
    day, _prio, price, source = max(candidates)
    # kho lưu close float32 → nhiễu ~1e-6 tương đối (22.700001 × 1000 →
    # GT hiện tại "454,000,015"); 6 chữ số có nghĩa đủ cho mọi thang giá
    price = float(f"{price:.6g}")
    return price, day, source


# Tripwire NGÀY MUA: %L/L cùng ngày vượt xa MỌI biên độ phiên hợp lệ (HOSE
# ±7% · HNX ±10% · UPCoM ±15%, chào sàn tới ±40%; mua đáy −N% đóng trần +N%
# cũng chỉ tới ~±hai lần biên) → gần như chỉ còn lệch đơn vị giá 1000×:
# giá bị chia 1000 → ~−99.9%, bị nhân 1000 → ~+99,900%. Ngưỡng ±7.5% cũ
# dán nhãn "chắc chắn sai" cho cả dữ liệu HNX/UPCoM đúng (review 21/07).
_UNIT_TRIPWIRE_LOSS_PCT = -90.0
_UNIT_TRIPWIRE_GAIN_PCT = 300.0


def _unit_suspect(buy_date: str, price_date: str, pnl_pct: float) -> bool:
    """True khi %L/L NGAY TRONG NGÀY MUA vượt ngưỡng nghi lệch đơn vị 1000×.
    Chỉ so khi price_date == buy_date (khác ngày: giá trôi hợp lệ không giới
    hạn — tripwire mù, đã có neo qua kho trong resolve_current_price lo)."""
    bd = str(buy_date or "")[:10]
    pd_ = str(price_date or "")[:10]
    if not bd or not pd_ or bd != pd_:
        return False
    return (pnl_pct <= _UNIT_TRIPWIRE_LOSS_PCT
            or pnl_pct >= _UNIT_TRIPWIRE_GAIN_PCT)


def _delete_label(row: dict, i: int) -> str:
    """Nhãn dòng i trong selectbox "Xoá vị thế". Streamlit lưu lựa chọn bằng NHÃN
    (nhãn trùng thì cái sau thắng) ⇒ hai lô giống hệt phải khác nhau ở ``#i+1``."""
    bd = str(row.get("buy_date") or "")[:10]
    return (f"{row['ticker']} ({row['qty']} cp @ {row['buy_price']:,.0f})"
            + (f" · mua {bd}" if bd else "") + f" · #{i + 1}")


_NAV_DTICK_MAX_SESSIONS = 10   # chuỗi ≤ ngưỡng: ép tick 1 ngày (nhãn lặp)
_ONE_DAY_MS = 86_400_000


def _nav_xaxis(n_sessions: int) -> dict:
    """Cấu hình trục X chart NAV: tick theo NGÀY (hết nhãn 00:00/12:00) + ẩn
    T7-CN (hết đoạn thẳng xuyên cuối tuần; ngày lễ VN vẫn tạo gap nhỏ — chấp
    nhận, không có lịch nghỉ lễ). Chuỗi ngắn ≤ _NAV_DTICK_MAX_SESSIONS phiên:
    plotly auto chia tick DƯỚI 1 ngày → nhãn lặp ("16/07 · 16/07 · 17/07…")
    — ép dtick đúng 1 ngày; chuỗi dài giữ auto (dtick cứng làm trục dày)."""
    xaxis: dict = {
        "tickformat": "%d/%m",
        "rangebreaks": [{"bounds": ["sat", "mon"]}],
    }
    if n_sessions <= _NAV_DTICK_MAX_SESSIONS:
        xaxis["dtick"] = _ONE_DAY_MS
    return xaxis


def render_portfolio_tab(warehouse: Path | str = DEFAULT_WAREHOUSE) -> None:
    """Render the Portfolio tab. Lazy imports Streamlit."""
    try:
        import streamlit as st
    except ImportError:
        print("[portfolio_tab] streamlit not available")
        return

    warehouse = Path(warehouse)
    st.markdown("### 💼 Danh mục đầu tư")

    # Cache theo rerun (review 21/07): resolver đọc TOÀN BỘ lịch sử parquet
    # của mã (gộp mọi file qua _close_series) cho TỪNG vị thế — không cache
    # thì mỗi rerun Streamlit đọc lại từ đầu. TTL ngắn để live mode vẫn tươi;
    # best-effort: streamlit quá cũ thiếu cache_data → gọi thẳng.
    _cache = getattr(st, "cache_data", None)
    _resolve_price = (_cache(ttl=60, show_spinner=False)(resolve_current_price)
                      if _cache else resolve_current_price)

    try:
        positions = _load_portfolio(warehouse)
    except (OSError, ValueError) as e:
        st.error(f"Không đọc được file danh mục `{_portfolio_path(warehouse)}` ({e}). "
                 "Đã khoá Thêm/Xoá để không ghi đè — sửa hoặc khôi phục file (Dropbox: "
                 "lịch sử phiên bản / bản conflicted copy) rồi tải lại trang.")
        return

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
                    _save_and_rerun(st, warehouse, positions + [{
                        "ticker": _pf_ticker,
                        "quantity": _pf_qty,
                        "buy_price": _pf_price,
                        "buy_date": str(_pf_date),
                    }])

        if positions:
            st.caption(f"{len(positions)} vị thế")
            if st.button("🗑 Xoá tất cả", key="pf_clear",
                          use_container_width=True):
                _save_and_rerun(st, warehouse, [])

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

        current_price, price_date, price_src = _resolve_price(
            ticker, buy_price, buy_date, warehouse)

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
            "price_date": price_date,
            "price_src": price_src,
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
    _any_band_warn = False
    for r in sorted(rows, key=lambda x: x["pnl"], reverse=True):
        _pc = "#10b981" if r["pnl"] >= 0 else "#ef4444"
        _ps = "+" if r["pnl"] >= 0 else ""
        _bg = "#0d1117"
        _cur_cell = "—"
        if r["current_price"] > 0:
            _meta = ""
            if r.get("price_date"):
                _meta = (" <span style='font-size:9px;color:#6b7280'>"
                         f"{r['price_date'][5:]}·{r.get('price_src', '')}"
                         "</span>")
            _cur_cell = f"{r['current_price']:,.0f}{_meta}"
        _band_warn = _unit_suspect(
            r.get("buy_date", ""), r.get("price_date", ""), r["pnl_pct"])
        _any_band_warn = _any_band_warn or _band_warn
        _warn_mark = "⚠ " if _band_warn else ""
        _rows_html += (
            f"<tr style='background:{_bg}'>"
            f"<td style='{_td}text-align:left;color:#60a5fa;font-weight:600'>{r['ticker']}</td>"
            f"<td style='{_td}color:#9ca3af'>{r['qty']:,}</td>"
            f"<td style='{_td}color:#9ca3af'>{r['buy_price']:,.0f}</td>"
            f"<td style='{_td}color:#e5e7eb'>{_cur_cell}</td>"
            f"<td style='{_td}color:#9ca3af'>{r['invested']:,.0f}</td>"
            f"<td style='{_td}color:#e5e7eb'>{r['current_val']:,.0f}</td>"
            f"<td style='{_td}color:{_pc};font-weight:600'>{_ps}{r['pnl']:,.0f}</td>"
            f"<td style='{_td}color:{_pc};font-weight:600'>{_warn_mark}{_ps}{r['pnl_pct']:.2f}%</td>"
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
    if _any_band_warn:
        st.caption(
            "⚠ %Lãi/Lỗ ngay trong NGÀY MUA vượt xa mọi biên độ phiên hợp lệ "
            "(HOSE ±7% · HNX ±10% · UPCoM ±15%, chào sàn tới ±40%) — nghi "
            "lệch đơn vị giá 1000× (VND ↔ nghìn đồng); soi cột Giá hiện tại "
            "(ngày·nguồn) và kiểm tra nguồn giá."
        )

    # ── Net-worth curve — NAV danh mục vs VNINDEX (món DojoAgents 20/07) ──
    st.markdown("---")
    st.markdown("#### 📈 Giá trị danh mục theo thời gian (NAV)")
    try:
        from vnstock_networth import load_networth
        _nw_load = (_cache(ttl=300, show_spinner=False)(load_networth)
                    if _cache else load_networth)
        _nw = _nw_load(warehouse)
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
                _xaxis_nw = _nav_xaxis(len(_nw["dates"]))
                _fig_nw.update_layout(
                    height=320,
                    margin=dict(l=0, r=0, t=10, b=0),
                    yaxis=dict(title="Rebase 100"),
                    xaxis=_xaxis_nw,
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

            # caption stats: builder DÙNG CHUNG với CLI (parity by
            # construction) — gate ẩn vol/Sharpe/Calmar khi < 10 phiên
            from vnstock_networth import summary_parts as _nw_summary
            st.caption("📊 " + " · ".join(_nw_summary(_nw)))

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
            # format sẵn thành CHUỖI — pandas 3 hiển thị float đầy đủ
            # ("56.200000") và int không ngăn nghìn trong st.dataframe
            _tbl_rows = []
            for s, pct in _sectors_sorted:
                _bench_pct = _VN30_BENCH.get(s, 0.0)
                _diff = pct - _bench_pct
                _pnl_s = _sector_pnl.get(s, 0.0)
                _tbl_rows.append({
                    "Ngành": f"{SECTOR_ICONS.get(s,'•')} {s}",
                    "Danh mục %": f"{pct:.1f}",
                    "VN30 %": f"{_bench_pct:.1f}",
                    "Lệch (pp)": f"{_diff:+.1f}",
                    "Lãi/Lỗ (VND)": f"{int(_pnl_s):+,}",
                })
            import pandas as _pd
            _df_exp = _pd.DataFrame(_tbl_rows)

            def _color_diff(val):
                try:
                    _v = float(str(val).replace(",", ""))
                except (TypeError, ValueError):
                    return "color: #94a3b8"
                if _v > 2:
                    return "color: #22c55e"
                elif _v < -2:
                    return "color: #ef4444"
                return "color: #94a3b8"

            # pandas ≥ 2.1 đổi Styler.applymap → Styler.map; pandas 3 BỎ HẲN
            # applymap — ưu tiên .map, fallback .applymap cho pandas cũ.
            _styler = _df_exp.style
            _style_map = getattr(_styler, "map", None) or _styler.applymap
            st.dataframe(
                _style_map(_color_diff, subset=["Lệch (pp)"]),
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
    # Option là CHỈ SỐ dòng; nhãn vẫn phải DUY NHẤT vì Streamlit serialize bằng nhãn.
    _del_i = st.selectbox(
        "Xoá vị thế", options=[None, *range(len(rows))], key="pf_del_select",
        format_func=lambda i: "—" if i is None else _delete_label(rows[i], i))
    if _del_i is not None:
        st.button("🗑 Xoá vị thế này", key="pf_del_btn", on_click=_delete_position,
                  args=(st, warehouse, rows[_del_i]["idx"]))
