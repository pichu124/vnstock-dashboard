"""dashboard/assets_tab.py — tab "💱 Hàng hoá & Tiền tệ" (P2 đa tài sản, U83).

Nhãn tab dùng 💱 chứ không 🪙: 🪙 (Emoji 13) không có trong font emoji của Windows 10 ⇒ desktop vẽ
thành ô vuông (10/10). Mục brief vẫn 🪙 — Telegram tự vẽ emoji.

CHỈ ĐỌC kho `data_warehouse/assets` (P1, `docs/THIET-KE-DA-TAI-SAN.md` §9): số do task tin mỗi giờ
(🖥️ desktop) + MCP Finhay/SSI ghi; tab không gọi mạng, không gọi LLM. Số tính ở
`vnstock_assets_view` (thuần, có test) — file này chỉ vẽ.

Quy ước biểu đồ: một trục y (chênh % tách biểu đồ riêng khỏi giá), đường 2px, ≥2 chuỗi thì có chú
thích, màu theo THỰC THỂ (Brent luôn xanh, WTI luôn cam…) lấy 3 ô đầu bảng màu đã kiểm mù màu;
đường trần/sàn tỷ giá là đường THAM CHIẾU xám nét đứt, không phải một chuỗi.
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard import ui
from dashboard.theme import PLOTLY_BG, SERIES, TOKENS, rgba

_C1, _C2, _C3 = SERIES[:3]                          # xanh · cam · tím (ô 1–3 bảng màu chung)
_GRID = rgba(TOKENS["text_muted"], 0.15)
_REF = "rgba(150,150,150,0.85)"
_RANGES = {"3 tháng": 92, "6 tháng": 183, "1 năm": 366, "3 năm": 1096, "Tất cả": None}
_SPARSE_POINTS = 3
# Hàm ĐỌC KHO parquet (`va.load`): kết quả chỉ phụ thuộc kho + tham số + ngày ⇒ đệm theo `_store_stamp`.
# Hàm đọc `_meta` (run_info, estimate, agreement_table) và hàm định dạng không vào đây — đi thẳng.
_STORE_READERS = {
    "vnstock_assets_view": {"card", "frame", "premium_frame", "dealer_table", "curve_snapshots",
                            "spread_series", "usd_band_frame"},
    "vnstock_assets": {"curve_spreads", "usd_ceiling_room_pct", "central_dating"},
}


def render_assets_tab() -> None:
    try:
        import vnstock_assets as va
        import vnstock_assets_view as av
    except ImportError as e:
        ui.show_error("Không nạp được kho tài sản.", e)
        return
    ui.page_header("Hàng hoá & Tiền tệ", "Vàng · dầu · USD")
    info = av.run_info()
    if not info["python_at"] and not av.card("XAU"):
        st.info("Kho tài sản trống — 🖥️ DESKTOP, ngoài khung pipeline: "
                "`python run.py assets --backfill --with-mcp` (một lần), sau đó task tin mỗi giờ tự cập nhật.")
        return
    st.caption(f"Chỉ đọc kho `data_warehouse/assets` · lượt Python {_hhmm(info['python_at'])} "
               f"({info['python_status'] or '—'}) · MCP {_hhmm(info['mcp_at'])} ({info['mcp_status'] or '—'}) "
               f"· máy {info['machine'] or '—'} · task tin 🖥️ cập nhật mỗi giờ")
    rng = st.radio("Khung biểu đồ", list(_RANGES), index=2, horizontal=True, key="assets_range")
    days = _RANGES.get(rng)
    start = (date.today() - timedelta(days=days)).isoformat() if days else None
    # Mỗi lượt rerun (đổi radio; Streamlit cũ không tab lười thì cả 4 mục) ⇒ đọc kho qua cache.
    stamp = _store_stamp(va)
    va, av = _Cached(va, stamp), _Cached(av, stamp)
    from dashboard.news_tab import lazy_tabs, tab_open
    t_gold, t_oil, t_usd, t_link = lazy_tabs(
        st, ["🥇 Vàng", "🛢️ Dầu", "💵 USD", "🔗 Liên kết cổ phiếu"], key="assets_subtab")
    for tab, fn, name in ((t_gold, _render_gold, "Vàng"), (t_oil, _render_oil, "Dầu"),
                          (t_usd, _render_usd, "USD"), (t_link, _render_links, "Liên kết cổ phiếu")):
        if not tab_open(tab):
            continue
        with tab:
            try:
                fn(va, av, start)
            except Exception as e:                                 # noqa: BLE001
                st.warning(f"Mục {name} lỗi khi vẽ."
                           + (f" {type(e).__name__}: {e}" if ui.diag_on() else ""))
    with st.expander("🔍 Đối chiếu nguồn MCP ↔ Python (ngày đã đóng)"):
        try:
            tbl = av.agreement_table()
        except Exception as e:                                     # noqa: BLE001
            tbl = None
            st.warning("Đối chiếu nguồn lỗi."
                       + (f" {type(e).__name__}: {e}" if ui.diag_on() else ""))
        if tbl is not None and len(tbl):
            st.dataframe(tbl, hide_index=True, use_container_width=True)
        elif tbl is not None:
            st.caption("Chưa có ngày chung — sổ giá theo nguồn bắt đầu ghi từ lượt mỗi giờ đầu tiên sau khi cập nhật.")
        st.caption(f"MCP Finhay/SSI là nguồn ưu tiên; mỗi chuỗi so với nguồn Python cùng công cụ trên "
                   f"{va.GATE_N} ngày chung gần nhất: đạt = tối đa {va.GATE_MAX_BAD} ngày lệch quá ngưỡng. "
                   "Lệch kéo dài ⇒ đặt VNSTOCK_ASSETS_DEMOTE=<KHOÁ>:finhay trong .env để nguồn Python thắng.")


# ── đệm đọc kho ──────────────────────────────────────────────────────────────
def _store_stamp(va) -> tuple:
    """Khoá làm tươi: hôm nay (card tính tuổi số theo ngày) + số file + mtime mới nhất trong kho
    (ghi nguyên tử = file mới ⇒ mtime mới; xoá conflicted copy ⇒ đổi số file)."""
    mtimes = [p.stat().st_mtime_ns for p in Path(va.ASSETS_DIR).rglob("*.parquet")]
    return date.today().isoformat(), len(mtimes), max(mtimes, default=0)


@st.cache_data(show_spinner=False, max_entries=256)
def _cached_read(module: str, name: str, args: tuple, kwargs: tuple, stamp: tuple):
    return getattr(importlib.import_module(module), name)(*args, **dict(kwargs))


class _Cached:
    """`va`/`av` cho các hàm vẽ: tên trong `_STORE_READERS` đi qua `_cached_read`, còn lại đi thẳng."""

    def __init__(self, mod, stamp: tuple):
        self._mod, self._stamp = mod, stamp

    def __getattr__(self, name):
        if name not in _STORE_READERS.get(self._mod.__name__, ()):
            return getattr(self._mod, name)
        return lambda *a, **k: _cached_read(self._mod.__name__, name, a, tuple(sorted(k.items())),
                                            self._stamp)


# ── tiện ích vẽ ──────────────────────────────────────────────────────────────
def _hhmm(ts) -> str:
    s = str(ts or "")
    return f"{s[11:16]} {s[8:10]}/{s[5:7]}" if len(s) >= 16 else "—"


def _metric(col, c: "dict | None", *, label: "str | None" = None, unit_note: bool = True) -> None:
    """Ô số: giá + % đổi 1 phiên (delta) + dòng phụ 1 tuần/1 tháng/YTD + nguồn, ngày, tuổi."""
    import vnstock_assets_view as av
    with col:
        if not c:
            st.metric(label or "—", "—")
            st.caption("chưa có dữ liệu")
            return
        d1 = c["chg"].get("1 phiên")
        st.metric(label or c["label"], av.fmt_value(c["value"], c["unit"]),
                  delta=f"{d1:+.2f}% 1 phiên" if d1 is not None else None,
                  delta_color="off" if d1 is not None and abs(d1) < 0.005 else "normal")
        stale = f" · ⚠️ cũ {c['age']} ngày" if c["stale"] else ""
        st.caption(f"{av.fmt_changes(c['chg'], skip=('1 phiên',))}  \n"
                   f"{c['unit'] if unit_note else ''} · {c['source']} · {c['date']}{stale}")


def _fig(series: list, *, height: int = 300, yfmt: str = ",.2f", hlines: "list | None" = None):
    """series = [(tên, Series, màu, nét)] — một trục, rê chuột theo trục x."""
    import plotly.graph_objects as go
    fig = go.Figure()
    for name, ser, color, dash in series:
        ser = ser.dropna()
        if not len(ser):
            continue
        sparse = len(ser) < _SPARSE_POINTS              # 1–2 điểm vẽ đường thì không thấy gì
        fig.add_trace(go.Scatter(x=ser.index, y=ser.values, name=name,
                                 mode="lines+markers" if sparse else "lines",
                                 line={"color": color, "width": 2, "dash": dash},
                                 marker={"size": 9, "color": color},
                                 hovertemplate=f"{name}: %{{y:{yfmt}}}<extra></extra>"))
    for name, ser in hlines or []:
        ser = ser.dropna()
        if len(ser):
            fig.add_trace(go.Scatter(x=ser.index, y=ser.values, name=name, mode="lines",
                                     line={"color": _REF, "width": 1.5, "dash": "dash"},
                                     hovertemplate=f"{name}: %{{y:{yfmt}}}<extra></extra>"))
    fig.update_layout(height=height, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      hovermode="x unified", showlegend=len(fig.data) >= 2,
                      legend={"orientation": "h", "y": 1.12, "x": 0},
                      **PLOTLY_BG,
                      xaxis={"showgrid": False, "tickformat": "%d/%m/%y", "hoverformat": "%d/%m/%Y"},
                      yaxis={"gridcolor": _GRID, "tickformat": yfmt})
    return fig


def _chart(title: str, series: list, **kw) -> None:
    if not any(len(s[1].dropna()) for s in series):
        return
    ui.section(title)
    try:
        st.plotly_chart(_fig(series, **kw), use_container_width=True)
    except ImportError:
        st.line_chart(pd.concat({s[0]: s[1] for s in series}, axis=1))


# ── 🥇 Vàng ──────────────────────────────────────────────────────────────────
def _render_gold(va, av, start) -> None:
    c = st.columns(4)
    _metric(c[0], av.card("XAU"))
    _metric(c[1], av.card("GOLD_SJC_BAR"), label="SJC miếng (bán)")
    _metric(c[2], av.card("GOLD_SJC_RING"), label="SJC nhẫn (bán)")
    prem = av.premium_frame(start=start)
    with c[3]:
        if len(prem):
            last = prem.iloc[-1]
            wk = prem["pct"][prem.index <= prem.index[-1] - pd.Timedelta(days=7)]
            d_wk = f"{last['pct'] - wk.iloc[-1]:+.2f} điểm % 1 tuần" if len(wk) else None
            st.metric("SJC miếng đắt hơn vàng TG", f"{last['pct']:+.2f}%", delta=d_wk, delta_color="off")
            st.caption(f"vàng TG quy đổi {last['world']:,.0f} đ/lượng · {prem.index[-1].date()}")
        else:
            st.metric("SJC miếng đắt hơn vàng TG", "—")
            st.caption("chưa đủ dữ liệu (cần SJC + vàng TG + USD/VND)")

    ui.section("Giá vàng 5 đại lý (đồng/lượng)")
    tbl = av.dealer_table()
    if len(tbl):
        show = tbl.drop(columns=["Cũ"]).copy()
        for col in ("Mua", "Bán", "Bán − SJC miếng"):
            show[col] = show[col].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
        for col in ("Chênh mua–bán %", "Chênh vs TG %"):
            show[col] = show[col].map(lambda v: f"{v:.2f}" if pd.notna(v) else "—")
        st.dataframe(show, hide_index=True, use_container_width=True)
        if tbl["Cũ"].any():
            st.caption("⚠️ Có sản phẩm chưa có giá hôm nay: " + ", ".join(
                f"{r['Đại lý']} {r['Loại']} ({r['Ngày']})" for r in tbl[tbl["Cũ"]].to_dict("records")))
    else:
        st.caption("Chưa có giá đại lý (MCP Finhay).")

    if len(prem):
        _chart("SJC miếng (bán) và vàng thế giới quy đổi — đồng/lượng",
               [("SJC miếng bán", prem["ask"], _C1, "solid"),
                ("Vàng TG quy đổi", prem["world"], _C2, "solid")], yfmt=",.0f")
        _chart("Chênh SJC miếng so vàng TG — %", [("Chênh %", prem["pct"], _C1, "solid")],
               height=220, yfmt=".1f")
    xau = av.frame("XAU", start=start)
    _chart("Vàng thế giới giao ngay — USD/oz", [("XAU", xau["close"], _C1, "solid")])
    st.caption("Vàng TG = giá giao ngay (XAU), không phải hợp đồng tương lai. Quy đổi: XAU × USD/VND "
               "thị trường × 37,5/31,1035 oz/lượng. Đại lý: giá BÁN là giá chính.")


# ── 🛢️ Dầu ──────────────────────────────────────────────────────────────────
def _render_oil(va, av, start) -> None:
    c = st.columns(4)
    _metric(c[0], av.card("BRENT"), label="Brent HĐTL tháng gần")
    _metric(c[1], av.card("WTI"), label="WTI HĐTL tháng gần")
    est = av.estimate("WTI_SPOT_EST") or {}
    with c[2]:
        if est.get("value"):
            st.metric("WTI giao ngay (ước tính)", f"{est['value']:,.2f}")
            st.caption(f"±{est['band_pct']}% · neo EIA {est['anchor']:,.2f} ngày {est['anchor_date']} "
                       f"· {est['h']} phiên · {est['date']}")
        else:
            st.metric("WTI giao ngay (ước tính)", "—")
            st.caption(est.get("hidden") or "chưa có ước tính")
    spread = av.spread_series(start=start)
    with c[3]:
        if len(spread):
            wk = spread[spread.index <= spread.index[-1] - pd.Timedelta(days=7)]
            st.metric("Brent − WTI", f"{spread.iloc[-1]:+.2f} USD",
                      delta=f"{spread.iloc[-1] - wk.iloc[-1]:+.2f} USD 1 tuần" if len(wk) else None,
                      delta_color="off")
            st.caption(f"USD/thùng · HĐTL tháng gần · {spread.index[-1].date()}")
        else:
            st.metric("Brent − WTI", "—")

    _render_curves(va, av)
    br, wt = av.frame("BRENT", start=start), av.frame("WTI", start=start)
    _chart("Giá HĐTL tháng gần — USD/thùng",
           [("Brent", br["close"], _C1, "solid"), ("WTI", wt["close"], _C2, "solid")])
    _chart("Chênh Brent − WTI — USD/thùng", [("Brent − WTI", spread, _C1, "solid")],
           height=220)
    with st.expander("Giá giao ngay EIA (chậm 3–9 ngày) — vì sao Brent giao ngay bị ẩn"):
        rows = []
        for key in ("BRENT_SPOT", "WTI_SPOT"):
            cc = av.card(key)
            if cc:
                rows.append({"Chuỗi": cc["label"], "Giá": f"{cc['value']:,.2f}", "Ngày": cc["date"],
                             "Trễ (ngày)": cc["age"], "Nguồn": cc["source"]})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Giá giao ngay EIA (Dated Brent/WTI Cushing) ra chậm 3–9 ngày. WTI giao ngay được ước "
                   "tính trong ngày = số EIA gần nhất × biến động HĐTL tháng gần, chỉ khi ≤3 phiên (sai số "
                   "đo p90 1,64%). Brent giao ngay lệch HĐTL tới ~25% và ước tính sai p90 5,7% ⇒ không "
                   "hiện; dùng đường cong HĐTL bên trên làm thước \"thị trường vật chất căng\".")


def _render_curves(va, av) -> None:
    snaps = {k: av.curve_snapshots(k) for k in ("CURVE_BRENT", "CURVE_WTI")}
    if not any(s["latest"] for s in snaps.values()):
        return
    import plotly.graph_objects as go
    ui.section("Đường cong HĐTL theo tháng đáo hạn — USD/thùng")
    fig = go.Figure()
    notes = []
    for key, name, color in (("CURVE_BRENT", "Brent", _C1), ("CURVE_WTI", "WTI", _C2)):
        s = snaps[key]
        for which, dash in (("latest", "solid"), ("prior", "dot")):
            if not s[which]:
                continue
            d, pts = s[which]
            fig.add_trace(go.Scatter(
                x=[_month_label(m) for _, m, _ in pts], y=[p for _, _, p in pts],
                name=f"{name} {d[8:10]}/{d[5:7]}", mode="lines+markers",
                line={"color": color, "width": 2, "dash": dash}, marker={"size": 8},
                hovertemplate=f"{name} %{{x}}: %{{y:,.2f}}<extra>{d}</extra>"))
        cs = va.curve_spreads(key)
        if cs:
            notes.append(f"{name}: M1−M2 {cs['m1_m2']['usd']:+.2f} USD ({cs['m1_m2']['pct']:+.2f}%) · "
                         f"M1−{cs['m1_m6']['to']} {cs['m1_m6']['usd']:+.2f} USD ⇒ "
                         f"{'backwardation (gần đắt hơn xa — cung căng)' if cs['shape'] == 'backwardation' else 'contango (xa đắt hơn gần — cung dư)'}")
    fig.update_layout(height=300, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      hovermode="closest", legend={"orientation": "h", "y": 1.12, "x": 0},
                      **PLOTLY_BG,
                      xaxis={"showgrid": False, "type": "category"},
                      yaxis={"gridcolor": _GRID})
    st.plotly_chart(fig, use_container_width=True)
    st.caption("  \n".join(notes) + "  \nNét liền = ảnh mới nhất · nét chấm = ảnh ~1 tuần trước "
               "(chỉ có từ khi lượt mỗi giờ bắt đầu chụp).")


def _month_label(m: str) -> str:
    return f"{m[5:7]}/{m[:4]}" if m and len(m) >= 7 else str(m)


# ── 💵 USD ──────────────────────────────────────────────────────────────────
def _render_usd(va, av, start) -> None:
    c = st.columns(3)
    _metric(c[0], av.card("DXY"), label="DXY (ICE)")
    est = av.estimate("USD_BROAD_EST") or {}
    with c[1]:
        if est.get("value"):
            st.metric("Chỉ số USD rộng (ước tính)", f"{est['value']:,.2f}")
            st.caption(f"±{est['band_pct']}% · neo Fed {est['anchor']:,.2f} ngày {est['anchor_date']} "
                       f"· {est['h']} phiên · {est['date']}")
        else:
            st.metric("Chỉ số USD rộng (ước tính)", "—")
            st.caption(est.get("hidden") or "chưa có ước tính")
    _metric(c[2], av.card("USDVND"), label="USD/VND thị trường")

    c = st.columns(4)
    _metric(c[0], av.card("USDVND_VCB"), label="Vietcombank bán")
    _metric(c[1], av.card("USD_CENTRAL"), label="Tỷ giá trung tâm NHNN")
    _metric(c[2], av.card("USD_SBV_REF"), label="Giá bán tham khảo NHNN")
    room = va.usd_ceiling_room_pct()
    with c[3]:
        if room:
            st.metric("VCB bán còn cách trần", f"{room['pct']:.2f}%")
            st.caption(f"trần {room['ceiling']:,} = trung tâm {room['central']:,.0f} × 1,05 "
                       f"(ngày {room['central_date']})")
        else:
            st.metric("VCB bán còn cách trần", "—")

    band = av.usd_band_frame(start=start)
    if len(band):
        _chart("Tỷ giá USD/VND trong biên ±5% — đồng",
               [("Vietcombank bán", band["vcb_sell"], _C1, "solid"),
                ("Giá bán tham khảo NHNN", band["sbv_sell"], _C2, "solid"),
                ("Trung tâm NHNN", band["central"], _C3, "solid")],
               hlines=[("Trần (trung tâm × 1,05)", band["ceiling"])], yfmt=",.0f")
    dxy = av.frame("DXY", start=start)
    _chart("DXY (ICE) — điểm", [("DXY", dxy["close"], _C1, "solid")], height=240)
    broad = av.frame("USD_BROAD", start=start)["close"]
    est_s = av.frame("USD_BROAD_EST", start=start)["close"]
    _chart("Chỉ số USD rộng của Fed (01/2006 = 100) và ước tính trong ngày",
           [("Fed (chính thức, chậm ≤7 ngày)", broad, _C1, "solid"),
            ("Ước tính trong ngày", est_s, _C2, "dot")], height=240)
    cv = va.central_dating()
    if cv.get("n"):
        st.caption(f"Ngày tỷ giá trung tâm (kho, nguồn vnstock_data mbk đã dời 1 ngày lịch) so giá "
                   f"tham khảo NHNN {cv['n']} phiên: {cv['verdict']}. Giá tham khảo NHNN (SSI \"SBVN\") "
                   "KHÔNG phải tỷ giá trung tâm — ~70% phiên bằng trung tâm phiên trước.")


# ── 🔗 Liên kết cổ phiếu (P4) ────────────────────────────────────────────────
_EXPECT = {1: "+", -1: "−", None: "?"}


def _render_links(va, av, start) -> None:
    import vnstock_assets_links as al
    res = al.load()
    if not res.get("rows"):
        st.info("Chưa có số liên kết — pipeline tối (bước `assets`) tự tính sau khi đồng bộ giá; "
                "chạy tay: `python vnstock_assets_links.py`.")
        return
    st.caption(f"Đo {res['window']} phiên gần nhất (nền {res['window_long']} phiên) · tính "
               f"{_hhmm(res.get('as_of'))} · **beta riêng** = cổ phiếu đổi bao nhiêu % khi yếu tố đổi 1%, "
               f"SAU KHI trừ nhịp chung VNINDEX · chỉ tính là có quan hệ khi |t| ≥ {res['t_sig']} và "
               f"≥ {res['min_n']} phiên.")
    rows = []
    for r in res["rows"]:
        m, ml = r["w60"], r["w250"]
        rows.append({"Mã": r["ticker"], "Yếu tố": r["driver_label"] + (" (lệch 1 phiên)" if r["lag"] else ""),
                     "Kỳ vọng": _EXPECT.get(r["expected"], "?"),
                     "Beta riêng 60p": f"{m['beta']:+.2f}" if m["beta"] is not None else "—",
                     "t": f"{m['t']:+.1f}" if m["t"] is not None else "—",
                     "Tương quan 60p": f"{m['corr']:+.2f}" if m["corr"] is not None else "—",
                     "Phiên": m["n"], "Kết luận": r["verdict"],
                     "Beta riêng 250p": f"{ml['beta']:+.2f}" if ml["beta"] is not None else "—",
                     "Kênh truyền dẫn (giả thuyết)": r["why"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    found = [r for r in res["rows"] if r["verdict"].startswith("có")]
    if found:
        st.caption("Có quan hệ: " + " · ".join(
            f"{r['ticker']} ← {r['driver_label']}: 1% ⇒ {r['w60']['beta']:+.2f}%" for r in found))
    st.caption("Giá quốc tế (vàng TG, Brent, DXY) đóng cửa SAU phiên VN ⇒ phiên t so với biến động yếu tố tới "
               "ngày trước t; giá nội (vàng nhẫn, VCB) so cùng ngày. Quan hệ đo được là THỐNG KÊ quá khứ, "
               "không phải dự báo; \"không thấy\" nghĩa là 60 phiên qua kênh này không nổi lên trên nhịp thị trường.")

