"""dashboard/allocation_tab.py — sub-tab "🧭 Phân bổ" bên trong tab Tin tức (P5).

UI mỏng trên cache vnstock_allocation (P1/P3) + vnstock_gold + scorecard (P6):
  * Band hiện hành + bảng % + lý do từng input (nguồn + as_of) + hysteresis/
    tilt — thuần hiển thị trên allocation_state.json.
  * Nút "Tính lại band" = zero LLM (đọc cache). Nút "Tạo brief phân bổ" là
    chỗ DUY NHẤT gọi LLM (brief_type='allocation', cadence THÁNG, CHỈ
    dashboard — không đẩy Telegram, tham số duyệt #4).
  * Vàng: display-only, luôn kèm nhãn premium SJC. Scorecard: bảng kỳ tháng +
    log nguồn (xếp hạng để dành khi đủ mẫu).

Streamlit lazy-import trong render (mirror money_flow_tab).
"""
from __future__ import annotations

_BAND_ORDER = ("B0", "B1", "B2", "B3", "B4")


def render_allocation_subtab() -> None:
    import streamlit as st
    try:
        import vnstock_allocation as alloc
    except ImportError:
        st.error("Không tìm thấy `vnstock_allocation.py`.")
        return

    state = alloc.load_state()
    if state is None:
        st.info("Chưa có allocation state — bấm nút dưới hoặc chạy "
                "`python run.py allocation` (pipeline tối tự chạy).")
        if st.button("🔄 Tính band lần đầu", key="_al_first"):
            alloc.run_allocation()
            st.rerun()
        return

    _render_band(st, alloc, state)
    _render_reasons(st, state)
    _render_history(st, state)
    _render_gold(st)
    _render_scorecard(st)
    _render_brief(st)


def _render_band(st, alloc, state: dict) -> None:
    import pandas as pd
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("Band phân bổ (tháng)",
              f"{state['band']} — {state.get('band_label', '')}")
    c2.metric("Điểm tổng hợp", f"{state.get('score', 0):+.3f}",
              help="+1 = thuận lợi tài sản rủi ro; band đổi cần vượt ranh "
                   "giới ≥0.05 trong 2 phiên (hysteresis)")
    with c3:
        rt = state.get("report_tilt")
        if rt:
            st.info(f"📚 Tilt {rt['tilt']:+d} band từ {rt.get('n_reports')} báo "
                    f"cáo (stance CP {rt.get('stance_cp')}) — band data: "
                    f"{state.get('band_data')}")
        if state.get("pending"):
            p = state["pending"]
            st.warning(f"⏳ Chờ xác nhận đổi sang {p['band']} "
                       f"({len(p['dates'])}/2 phiên)")
        st.caption(f"Phiên {state.get('as_of', '?')} · cập nhật "
                   f"{state.get('updated_at', '?')}")

    st.dataframe(pd.DataFrame(
        [{"Lớp tài sản": cls, "Tỷ trọng đề xuất": f"{pct}%"}
         for cls, pct in (state.get("allocation") or {}).items()]),
        hide_index=True, use_container_width=True)
    if st.button("🔄 Tính lại band (đọc cache, không gọi LLM)", key="_al_refresh"):
        import vnstock_allocation as alloc2
        alloc2.run_allocation()
        st.rerun()


def _render_reasons(st, state: dict) -> None:
    import pandas as pd
    inputs = state.get("inputs") or []
    if not inputs:
        return
    st.markdown("##### 📊 Vì sao ở band này")
    st.dataframe(pd.DataFrame([{
        "Tín hiệu": r.get("label"), "Giá trị": r.get("value"),
        "Điểm": f"{r.get('score', 0):+.2f}", "Trọng số": r.get("weight"),
        "Nguồn": r.get("source"), "as_of": r.get("as_of"),
    } for r in inputs]), hide_index=True, use_container_width=True)


def _render_history(st, state: dict) -> None:
    hist = state.get("history") or []
    if len(hist) < 2:
        return
    st.markdown("##### 📈 Lịch sử band")
    import pandas as pd
    ser = pd.Series(
        {pd.to_datetime(h["date"]): _BAND_ORDER.index(h["band"])
         for h in hist if h.get("band") in _BAND_ORDER}).sort_index()
    st.line_chart(ser, height=160)
    st.caption("0 = B0 (tấn công) … 4 = B4 (phòng thủ)")


def _render_gold(st) -> None:
    try:
        import vnstock_gold as gold
    except ImportError:
        return
    g = gold.load_gold()
    if not g:
        st.caption("🥇 Vàng: chưa có cache — `python vnstock_gold.py --refresh` "
                   "trên máy có mạng.")
        return
    ch = g.get("change")
    extra = (f" ({'▲' if ch['dir'] > 0 else '▼'} {ch['pct']:+.2f}% so với "
             f"{ch['prev_as_of']})" if ch and ch.get("dir") else "")
    st.caption(f"🥇 Vàng {g['value']:,.2f} USD/oz — as_of {g['as_of']}{extra} · "
               f"**{g['note']}**")


def _render_scorecard(st) -> None:
    try:
        import vnstock_scorecard as sc
    except ImportError:
        return
    data = sc.load_scorecard()
    if not data:
        return
    st.markdown("##### 🗂 Scorecard hồi tố")
    import pandas as pd
    periods = data.get("periods") or []
    if periods:
        st.dataframe(pd.DataFrame([{
            "Kỳ": f"{p['period_start']} → {p['period_end']}",
            "Band": p["band"],
            "Danh mục %": p["port_ret_pct"],
            "B2 %": p["baseline_b2_ret_pct"],
            "Δ vs B2 (pp)": p["delta_vs_b2"],
            "Phủ data %": p["coverage_pct"],
        } for p in periods]), hide_index=True, use_container_width=True)
        st.caption("Return theo PROXY THÔ (VNINDEX / −Δyield 10Y×7 / lãi suất "
                   "điều hành / vàng spot / USD-VND) — xem nhãn trong "
                   "`vnstock_scorecard.py --show`.")
    else:
        st.caption("Chưa đủ kỳ tháng hoàn tất (cần history ≥ 2 tháng).")
    srcs = data.get("sources") or []
    if srcs:
        with st.expander(f"Log nguồn báo cáo ({len(srcs)} dòng — xếp hạng để "
                         "dành khi đủ mẫu)"):
            st.dataframe(pd.DataFrame(srcs), hide_index=True,
                         use_container_width=True)


def _render_brief(st) -> None:
    st.markdown("##### 📝 Brief phân bổ (khung tháng — chỉ dashboard)")
    try:
        import vnstock_brief as vb
        import vnstock_memory as mem
    except ImportError:
        return
    latest = next((b for b in mem.recent_briefs("allocation", limit=1)), None)
    if latest:
        with st.expander(f"Brief gần nhất ({(latest.get('created_at') or '')[:16]}"
                         f" · {latest.get('agent_name')})", expanded=False):
            st.markdown(latest.get("output") or "")
    if st.button("📝 Tạo brief phân bổ mới (gọi LLM)", key="_al_brief"):
        with st.spinner("Đang tạo brief phân bổ…"):
            results = vb.generate_brief("allocation", force=True)
        shown = False
        # Lọc key "_" TRƯỚC rồi mới mổ tuple (mirror brief_run_panel):
        # results còn chở metadata (_brief_ids = list N id, _warnings =
        # dict) — mổ (text, err) ngay trong câu for là nổ "too many values
        # to unpack" đúng lúc brief THÀNH CÔNG nhiều agent (user bắt 13/08,
        # ngay lần bấm nút thật đầu tiên).
        for name, payload in results.items():
            if name.startswith("_"):
                continue
            text, err = payload
            if text:
                st.markdown(f"**{name}:**")
                st.markdown(text)
                shown = True
            elif err:
                st.caption(f"{name}: {err}")
        if not shown:
            st.error("Không agent nào tạo được brief — kiểm tra key .env.")
