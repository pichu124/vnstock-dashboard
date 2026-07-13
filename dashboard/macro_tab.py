"""dashboard/macro_tab.py — sub-tab "🌐 Vĩ mô" bên trong tab Tin tức.

Thuần HIỂN THỊ trên cache sẵn có — KHÔNG fetcher mới, KHÔNG gọi LLM (scope
"UI mỏng" chốt 2026-07-08; registry vĩ mô đã cap 10 chỉ số):
  * ``macro_indicators.json``  → bảng chỉ số + áp lực vĩ mô + chart lịch sử
  * ``market_news_cache.json`` → tin vĩ mô/thị trường theo ngày (retention 30d)
  * ``brief_memory.db``        → đọc lại mục 🌐 Vĩ mô / 🎯 TLDR của brief cũ

Data refresh vẫn qua pipeline (`run.py all` 18:00) / nút bên tab Thị trường —
tab này chỉ đọc.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

_SENT_ICON = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}
_LINE_COLOR = "#4c78a8"          # 1 series duy nhất — xanh dịu, ổn cả 2 theme


def render_macro_subtab() -> None:
    try:
        import vnstock_macro as mac
    except ImportError:
        st.error("Không tìm thấy `vnstock_macro.py`.")
        return

    _render_indicators(mac)
    _render_history_chart(mac)
    _render_macro_news()
    _render_brief_archive()


# ── 1) Bảng chỉ số hiện tại ──────────────────────────────────────────────────

def _render_indicators(mac) -> None:
    st.markdown("##### 📊 Chỉ số vĩ mô hiện tại")
    macro = mac.load_macro()
    if not macro:
        st.info("Cache vĩ mô rỗng — chạy `python vnstock_macro.py --refresh` "
                "(pipeline tối tự chạy bước này).")
        return
    rows = []
    for ind in macro:
        fc = mac.fmt_change(ind)
        rows.append({
            "Chỉ số": ind["label"],
            "Giá trị": mac.fmt_value(ind),
            "Thay đổi": (f"{fc[0]} {fc[1]} ({fc[2]})" if fc else "—"),
            "Tính đến": ind["as_of"],
            "Nguồn": ind["source"] or "—",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    p = mac.macro_pressure_score(macro)
    if p:
        icon = "🔴" if p["dir"] < 0 else ("🟢" if p["dir"] > 0 else "⚪")
        st.caption(f"{icon} Áp lực vĩ mô: **{p['label']}** (score {p['score']:+.2f})")
    else:
        st.caption("⚪ Áp lực vĩ mô: ổn định — không có thay đổi đáng kể gần đây.")

    liq = mac.liquidity_spread(macro)
    if liq:
        icon = "🔴" if liq["dir"] < 0 else ("🟢" if liq["dir"] > 0 else "⚪")
        slope = (f" · dốc 10Y − ON = {liq['slope_10y_on']:+.2f} điểm %"
                 if liq.get("slope_10y_on") is not None else "")
        st.caption(f"{icon} Thanh khoản: LNH ON − lãi suất điều hành = "
                   f"**{liq['spread']:+.2f} điểm %** — {liq['label']}{slope}")

    ts = mac.term_spread(macro)
    if ts:
        worst = min(ts["dir"], ts.get("slope_dir", 0))
        icon = "🔴" if worst < 0 else "⚪"
        slope = (f" · dốc 10Y − 2Y = {ts['slope_2_10']:+.2f} điểm % — "
                 f"{ts['slope_label']}"
                 if ts.get("slope_2_10") is not None else "")
        st.caption(f"{icon} Kỳ hạn: 10Y − lãi suất điều hành = "
                   f"**{ts['spread']:+.2f} điểm %** — {ts['label']}{slope}")

    intl = mac.intl_spread(macro)
    if intl:
        icon = "🔴" if intl["dir"] < 0 else "⚪"
        st.caption(f"{icon} Quốc tế: VN10Y − US10Y = "
                   f"**{intl['spread']:+.2f} điểm %** — {intl['label']}")

    rem = mac.pmi_reminder(macro)
    if rem:
        st.warning(rem)
    xc = mac._load_cache().get("fx_crosscheck")
    if xc:
        st.warning(
            f"Tỷ giá er-api {xc['er_api']:,.0f} lệch {xc['diff_pct']:+.1f}% so "
            f"với VCB (VBMA {xc['vbma_vcb_mid']:,.0f}, ngày {xc['date']}) — "
            f"kiểm tra nguồn FX hoặc `--set usdvnd`.")


# ── 2) Chart lịch sử 1 chỉ số ────────────────────────────────────────────────

def _render_history_chart(mac) -> None:
    inds = (mac._load_cache().get("indicators") or {})
    plottable = {k: v for k, v in inds.items()
                 if len(v.get("history") or {}) >= 2}
    if not plottable:
        return                        # mới seed / 1 mốc — chưa có gì để vẽ
    st.markdown("##### 📈 Lịch sử chỉ số")
    key = st.selectbox(
        "Chỉ số", options=list(plottable),
        format_func=lambda k: plottable[k].get("label", k),
        key="_macro_hist_key", label_visibility="collapsed")
    ind = plottable[key]
    hist = ind["history"]
    ser = pd.Series({pd.to_datetime(d): float(v) for d, v in hist.items()},
                    name=ind.get("label", key)).sort_index()
    try:
        import plotly.graph_objects as go
        fig = go.Figure(go.Scatter(
            x=ser.index, y=ser.values, mode="lines+markers",
            line={"color": _LINE_COLOR, "width": 2}, marker={"size": 6},
            hovertemplate="%{x|%d/%m/%Y}: %{y:,.2f}<extra></extra>"))
        fig.update_layout(
            height=280, margin={"l": 10, "r": 10, "t": 10, "b": 10},
            showlegend=False, xaxis={"showgrid": False},
            yaxis={"gridcolor": "rgba(128,128,128,0.15)"})
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.line_chart(ser)
    st.caption(f"{len(ser)} mốc · gần nhất {max(hist)} · đơn vị {ind.get('unit', '')}"
               f" · nguồn {ind.get('source', '—')}")


# ── 3) Tin vĩ mô/thị trường theo ngày ────────────────────────────────────────

def _render_macro_news() -> None:
    st.markdown("##### 🗞️ Tin vĩ mô & thị trường theo ngày")
    try:
        from vnstock_news_feeds import _load_cache as _load_news
        items = _load_news()
    except Exception:
        items = []
    if not items:
        st.info("Chưa có tin trong cache — chạy `python run.py news` "
                "(pipeline tối tự chạy).")
        return
    days: dict[str, list[dict]] = {}
    for it in items:
        d = (it.get("_date_sort") or "")[:10]
        if d:
            days.setdefault(d, []).append(it)
    for i, d in enumerate(sorted(days, reverse=True)):
        with st.expander(f"📅 {d} — {len(days[d])} tin", expanded=(i == 0)):
            for it in days[d]:
                icon = _SENT_ICON.get((it.get("_sentiment") or "").lower(), "⚪")
                title = it.get("title", "")
                link = it.get("link", "")
                src = it.get("source_feed", "")
                head = f"[{title}]({link})" if link else title
                st.markdown(f"{icon} {head}  \n"
                            f"<span style='color:gray;font-size:0.85em'>{src}"
                            f"{' · ' + it['_impact'] if it.get('_impact') else ''}"
                            f"</span>", unsafe_allow_html=True)


# ── 4) Đọc lại phân tích vĩ mô từ brief đã lưu ───────────────────────────────

def _render_brief_archive() -> None:
    st.markdown("##### 📚 Phân tích vĩ mô từ brief (lưu trữ)")
    try:
        from vnstock_brief import brief_section
        from vnstock_memory import recent_briefs
        briefs = [b for b in recent_briefs(limit=60)
                  if b.get("output") and len(b["output"]) > 100]
    except Exception as e:                                   # noqa
        st.info(f"Chưa đọc được brief memory: {e}")
        return
    if not briefs:
        st.info("Chưa có brief nào trong memory.")
        return
    labels = {
        f"{b['brief_date']} · {b['brief_type']} · {b.get('agent_name', '')}": b
        for b in briefs
    }
    pick = st.selectbox("Chọn brief", options=list(labels),
                        key="_macro_brief_pick")
    b = labels[pick]
    macro_sec = brief_section(b["output"], "🌐")
    tldr_sec = brief_section(b["output"], "🎯")
    if tldr_sec:
        st.markdown(tldr_sec)
    if macro_sec:
        st.markdown(macro_sec)
    if not (tldr_sec or macro_sec):
        st.caption("Brief này không có mục 🎯/🌐 (brief cũ trước khi thêm vĩ mô).")
    with st.expander("Xem toàn bộ brief"):
        st.markdown(b["output"])
        if b.get("user_rating"):
            st.caption(f"⭐ Đánh giá: {b['user_rating']}/5")
