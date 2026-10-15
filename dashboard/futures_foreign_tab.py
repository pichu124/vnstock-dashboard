"""dashboard/futures_foreign_tab.py — tab "📑 Phái sinh NN": vị thế ròng khối ngoại HĐTL VN30 (U88).

CHỈ ĐỌC kho `data_warehouse/futures` (bước pipeline `futures-foreign` 🖥️ ghi qua SSI MCP; lịch sử
nạp một lần từ seed trong repo). Không gọi mạng, không gọi LLM. Số tính ở
`vnstock_futures_foreign_view` (thuần, có test, dùng chung với mục 📑 của brief) — file này chỉ vẽ.

Quy ước biểu đồ (như tab 💱): một trục y mỗi biểu đồ — giá HĐ tháng gần là biểu đồ RIÊNG dưới vị
thế (chung trục thời gian), không phải trục y thứ hai; đường 2px; long/short là cặp phân cực
xanh/cam (ô 1–2 bảng màu đã kiểm mù màu); cột chồng theo kỳ hạn dùng 4 ô đầu theo thứ tự cố định;
đường 0 là đường THAM CHIẾU xám nét đứt.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

_LONG, _SHORT = "#3987e5", "#d95926"                       # xanh · cam (phân cực long/short)
_ROLE_COLORS = ("#3987e5", "#d95926", "#199e70", "#c98500")  # ô 1–4, thứ tự cố định theo kỳ hạn
_PRICE = "#199e70"
_REF = "rgba(150,150,150,0.85)"
_RANGES = {"3 tháng": 92, "6 tháng": 183, "1 năm": 366, "Tất cả": None}


def render_futures_foreign_tab() -> None:
    try:
        import vnstock_futures_foreign as ff
        import vnstock_futures_foreign_view as fv
    except ImportError as e:
        st.error(f"Không nạp được kho phái sinh: {e}")
        return
    st.markdown("### 📑 Phái sinh: vị thế ròng khối ngoại (HĐTL VN30)")
    df = ff.load()
    if not len(df):
        st.info("Kho phái sinh trống — ○ máy nào cũng được, một lần: `python run.py futures-foreign --seed` "
                "(lịch sử từ 08/2024, không gọi MCP). Sau đó bước pipeline 🖥️ tự cập nhật mỗi tối.")
        return
    pos = fv.positions(df)
    s = fv.summary(df, pos=pos)
    stt = ff.read_status()
    st.caption(f"Nguồn SSI (MCP) · khối ngoại mua − bán từng hợp đồng, cộng dồn từ phiên niêm yết · "
               f"phiên cuối {s['date']} · lượt cập nhật {_hhmm(stt.get('run_at'))} "
               f"({stt.get('status') or 'seed'}, máy {stt.get('machine') or '—'})")
    _warnings(ff, s)
    _tiles(fv, s)
    rng = st.radio("Khung biểu đồ", list(_RANGES), index=2, horizontal=True, key="ffut_range")
    days = _RANGES.get(rng)
    start = (date.fromisoformat(s["date"]) - timedelta(days=days)).isoformat() if days else None
    view = pos[pos["complete"]]
    view = view[view.index >= start] if start else view
    t_pos, t_term, t_hist, t_data = st.tabs(["📈 Vị thế & giá", "🧩 Theo kỳ hạn", "🗓 Lịch sử",
                                             "🔍 Dữ liệu"])
    for tab, fn, name in ((t_pos, lambda: _render_position(fv, view), "Vị thế & giá"),
                          (t_term, lambda: _render_terms(fv, s, pos, view), "Theo kỳ hạn"),
                          (t_hist, lambda: _render_history(fv, pos, s), "Lịch sử"),
                          (t_data, lambda: _render_data(fv, df, pos), "Dữ liệu")):
        with tab:
            try:
                fn()
            except Exception as e:                                 # noqa: BLE001
                st.warning(f"Mục {name} lỗi khi vẽ: {type(e).__name__}: {e}")


# ── đầu tab ──────────────────────────────────────────────────────────────────
def _hhmm(ts) -> str:
    v = str(ts or "")
    return f"{v[11:16]} {v[8:10]}/{v[5:7]}" if len(v) >= 16 else "—"


def _warnings(ff, s: dict) -> None:
    try:
        expect = ff.expected_session(pd.Timestamp.now().to_pydatetime()).isoformat()
    except Exception:                                              # noqa: BLE001
        expect = None
    if expect and s["date"] < expect:
        st.warning(f"Số cuối là phiên {s['date']}, chưa có phiên {expect} — 🖥️ DESKTOP: "
                   "`python run.py futures-foreign --force` (cần Claude Code + connector SSI).")
    if not s["complete"]:
        st.warning(f"Phiên {s['date']} mới có {s['n_live']}/4 hợp đồng lưu hành — tổng chưa đủ, "
                   "ô số và biểu đồ dùng phiên đủ gần nhất.")
    if s["uncertain"]:
        st.warning(f"Nguồn thiếu số khối ngoại vài phiên ⇒ sai số ước tính ±{s['err95']:,.0f} HĐ.")


def _tiles(fv, s: dict) -> None:
    c = st.columns(4)
    with c[0]:
        st.metric("Vị thế ròng (sau đáo hạn)", fv.side(s["after"]) if s["complete"] else "—",
                  delta=f"{s['chg1']:+,.0f} HĐ so phiên trước" if s.get("chg1") is not None else None,
                  delta_color="off")                    # đổi vị thế không có chiều tốt/xấu
        if s["expiring"]:
            st.caption(f"tính cả {s['expiring']} đáo hạn phiên này: {fv.side(s['total'])}")
        else:
            st.caption(f"{s.get('pct_rank', 0):.0f}% số phiên từ {s.get('data_from') or '—'} thấp hơn hoặc bằng")
    with c[1]:
        st.metric("Dòng lệnh khối ngoại phiên", f"{s['flow']:+,.0f} HĐ" if s["has_flow"] else "—")
        st.caption(f"mua {s['buy']:,.0f} · bán {s['sell']:,.0f} HĐ · phiên {s['date']}")
    with c[2]:
        cur, rec = s.get("streak"), s.get("streak_record")
        if cur:
            word = "long" if cur["sign"] > 0 else "short"
            st.metric("Chuỗi hiện tại", f"{word} {cur['n']} phiên")
            st.caption(f"từ {cur['start']}" + (f" · dài nhất phía {word}: {rec['n']} phiên" if rec else ""))
        else:
            st.metric("Chuỗi hiện tại", "—")
    with c[3]:
        if s.get("notional_bn"):
            st.metric("Giá trị danh nghĩa", f"≈ {s['notional_bn']:,.0f} tỷ đ")
            st.caption(f"|vị thế| × giá {s['front']} {s['front_close']:,.1f} × 100.000 đ/điểm")
        else:
            st.metric("Giá trị danh nghĩa", "—")


# ── tiện ích vẽ ──────────────────────────────────────────────────────────────
def _layout(fig, height: int, yfmt: str = ",.0f", legend: bool = False):
    fig.update_layout(height=height, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      hovermode="x unified", showlegend=legend,
                      legend={"orientation": "h", "y": 1.12, "x": 0},
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis={"showgrid": False, "tickformat": "%d/%m/%y", "hoverformat": "%d/%m/%Y"},
                      yaxis={"gridcolor": "rgba(128,128,128,0.15)", "tickformat": yfmt})
    return fig


def _plot(title: str, fig) -> None:
    st.markdown(f"###### {title}")
    st.plotly_chart(fig, use_container_width=True)


def _x(view):
    return pd.to_datetime(view.index)


def _zero(fig, x) -> None:
    import plotly.graph_objects as go
    if len(x):
        fig.add_trace(go.Scatter(x=[x[0], x[-1]], y=[0, 0], mode="lines", name="0", hoverinfo="skip",
                                 line={"color": _REF, "width": 1.5, "dash": "dash"}, showlegend=False))


# ── 📈 Vị thế & giá ──────────────────────────────────────────────────────────
def _render_position(fv, view) -> None:
    import plotly.graph_objects as go
    if not len(view):
        st.caption("Chưa có phiên đủ 4 hợp đồng trong khung này.")
        return
    x = _x(view)
    fig = go.Figure()
    _zero(fig, x)
    fig.add_trace(go.Scatter(x=x, y=view["after"], name="Vị thế ròng", mode="lines",
                             line={"color": _LONG, "width": 2},
                             hovertemplate="Vị thế ròng: %{y:+,.0f} HĐ<extra></extra>"))
    short = view["after"].where(view["after"] < 0)
    fig.add_trace(go.Scatter(x=x, y=short, name="Phiên short ròng", mode="lines",
                             line={"color": _SHORT, "width": 2.5}, connectgaps=False,
                             hovertemplate="Short ròng: %{y:+,.0f} HĐ<extra></extra>"))
    _plot("Vị thế ròng khối ngoại sau đáo hạn — hợp đồng (đoạn cam: short ròng)", _layout(fig, 320, legend=True))
    px = view["next_close"]
    fig = go.Figure(go.Scatter(x=x, y=px, name="Giá HĐ tháng gần", mode="lines",
                               line={"color": _PRICE, "width": 2},
                               hovertemplate="Giá HĐ tháng gần: %{y:,.1f}<extra></extra>"))
    _plot("Giá đóng cửa HĐ tháng gần (sau đáo hạn) — điểm", _layout(fig, 220, yfmt=",.0f"))
    colors = [_LONG if v >= 0 else _SHORT for v in view["flow"]]
    fig = go.Figure(go.Bar(x=x, y=view["flow"], marker={"color": colors}, name="Dòng lệnh ròng",
                           hovertemplate="Dòng lệnh ròng: %{y:+,.0f} HĐ<extra></extra>"))
    _plot("Dòng lệnh ròng khối ngoại mỗi phiên — hợp đồng (xanh: mua nhiều hơn bán · cam: ngược lại)",
          _layout(fig, 240))
    st.caption("Phiên đáo hạn: vị thế của hợp đồng đáo hạn được tất toán tiền mặt cuối phiên nên rời "
               "khỏi tổng — bước nhảy ngày đó KHÔNG phải dòng lệnh. Dòng lệnh ngày cuộn kỳ thường bù trừ "
               "(bán kỳ cũ, mua kỳ mới).")


# ── 🧩 Theo kỳ hạn ───────────────────────────────────────────────────────────
def _render_terms(fv, s, pos, view) -> None:
    import plotly.graph_objects as go
    st.markdown(f"###### Từng hợp đồng — phiên {s['date']}")
    tbl = fv.contract_table(s)
    if len(tbl):
        show = tbl.copy()
        for col in ("Vị thế ròng (HĐ)", "Dòng lệnh phiên (HĐ)"):
            show[col] = show[col].map(lambda v: f"{v:+,.0f}" if pd.notna(v) else "—")
        for col in ("Mua (HĐ)", "Bán (HĐ)", "KL khớp"):
            show[col] = show[col].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
        show["Giá đóng cửa"] = show["Giá đóng cửa"].map(lambda v: f"{v:,.1f}" if pd.notna(v) else "—")
        show["Khối ngoại % KL"] = show["Khối ngoại % KL"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—")
        st.dataframe(show, hide_index=True, use_container_width=True)
    roles = fv.role_frame(pos)
    roles = roles.loc[roles.index.isin(view.index)]
    if not len(roles):
        return
    x = _x(roles)
    fig = go.Figure()
    for name, color in zip(fv.ROLES, _ROLE_COLORS):
        fig.add_trace(go.Bar(x=x, y=roles[name], name=f"HĐ {name.lower()}", marker={"color": color},
                             hovertemplate=f"HĐ {name.lower()}: %{{y:+,.0f}} HĐ<extra></extra>"))
    fig.update_layout(barmode="relative", bargap=0.15)
    _plot("Vị thế ròng chia theo kỳ hạn (sau đáo hạn; gần nhất → xa nhất, cuộn theo mỗi kỳ đáo hạn)",
          _layout(fig, 320, legend=True))
    st.caption("Thứ tự kỳ hạn tính lại mỗi phiên: sau ngày đáo hạn, hợp đồng 'thứ 2' trở thành 'gần nhất'. "
               "VN30F luôn có 2 tháng gần + 2 quý gần.")


# ── 🗓 Lịch sử ───────────────────────────────────────────────────────────────
def _render_history(fv, pos, s) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("###### Cuối mỗi tháng")
        me = fv.month_end_table(pos)
        if len(me):
            show = me.drop(columns=["Phiên"]).copy()
            for col in ("Vị thế ròng (HĐ)", "Đổi trong tháng (HĐ)"):
                show[col] = show[col].map(lambda v: f"{v:+,.0f}" if pd.notna(v) else "—")
            show["Giá HĐ tháng gần"] = show["Giá HĐ tháng gần"].map(lambda v: f"{v:,.1f}" if pd.notna(v) else "—")
            st.dataframe(show, hide_index=True, use_container_width=True, height=420)
    with c2:
        for sign, title in ((-1, "Các chuỗi short ròng (dài nhất trước)"), (1, "Các chuỗi long ròng (dài nhất trước)")):
            st.markdown(f"###### {title}")
            t = fv.streak_table(pos, sign=sign, top=8)
            if len(t):
                t = t.copy()
                t["Sâu nhất (HĐ)"] = t["Sâu nhất (HĐ)"].map(lambda v: f"{v:+,.0f}")
                st.dataframe(t, hide_index=True, use_container_width=True)
            else:
                st.caption("chưa có chuỗi nào")
    ext = []
    if s.get("max_long"):
        ext.append(f"long lớn nhất {s['max_long']['value']:,.0f} HĐ ({s['max_long']['date']})")
    if s.get("max_short"):
        ext.append(f"short lớn nhất {abs(s['max_short']['value']):,.0f} HĐ ({s['max_short']['date']})")
    if ext:
        st.caption(f"Từ {s.get('data_from')}: " + " · ".join(ext)
                   + f" · {s.get('n_short', 0)}/{s.get('n_sessions', 0)} phiên short ròng. Chuỗi đầu dữ liệu "
                   "có thể đã bắt đầu sớm hơn (kho không có trước đó).")


# ── 🔍 Dữ liệu ───────────────────────────────────────────────────────────────
def _render_data(fv, df, pos) -> None:
    st.markdown("###### Dòng nguồn thiếu trường khối ngoại")
    q = fv.quality_table(df)
    if len(q):
        show = q.copy()
        for col in ("Dòng thiếu", "KL dòng thiếu", "KL hợp đồng"):
            show[col] = show[col].map(lambda v: f"{v:,.0f}")
        show["% KL thiếu"] = show["% KL thiếu"].map(lambda v: f"{v:.2f}")
        st.dataframe(show, hide_index=True, use_container_width=True)
    else:
        st.caption("Không có dòng nào thiếu.")
    st.caption("Sai số ước tính (95%) mỗi phiên: KL các dòng thiếu × tỷ lệ |ròng|/KL phân vị 95 (6% khi KL ≥ "
               "20.000 HĐ, 46% khi nhỏ hơn), cộng căn bậc hai tổng bình phương trên các hợp đồng đang mở. "
               "Tuần chuyển hệ KRX 05–14/05/2025 là đoạn duy nhất 'chưa chắc'.")
    cols = ["after", "total", "flow", "buy", "sell", "n_live", "expiring", "next_front", "next_close", "err95"]
    daily = pos[cols].rename(columns={"after": "vi_the_sau_dao_han", "total": "vi_the_gom_hd_dao_han",
                                      "flow": "dong_lenh_rong", "buy": "mua", "sell": "ban",
                                      "n_live": "so_hd_luu_hanh", "expiring": "hd_dao_han",
                                      "next_front": "hd_thang_gan", "next_close": "gia_hd_thang_gan",
                                      "err95": "sai_so_95"})
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Vị thế theo phiên (CSV)", daily.to_csv().encode("utf-8"),
                           file_name="vi_the_phai_sinh_khoi_ngoai.csv", mime="text/csv",
                           key="ffut_dl_daily")
    with c2:
        st.download_button("⬇️ Dòng gốc từng hợp đồng (CSV)", df.to_csv(index=False).encode("utf-8"),
                           file_name="phai_sinh_khoi_ngoai_hop_dong.csv", mime="text/csv",
                           key="ffut_dl_rows")
